import asyncio
import hmac
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Security, UploadFile
from fastapi.security import APIKeyHeader
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse

from . import alerts as alert_svc
from . import security, training
from .config import settings
from .db import now_iso
from .schemas import (AlertPatch, AuthorityIn, AuthorityPatch, CameraIn, CameraPatch, ConfirmIn,
                      DismissIn)
from .state import state

VID_EXT = (".mp4", ".avi", ".mov", ".mkv", ".m4v", ".webm")


# ------------------------------------------------------------------ auth / helpers
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)     # shows an "Authorize" button in /docs


def require_key(request: Request, header_key: Optional[str] = Security(api_key_header)):
    if not settings.api_key:
        return
    key = header_key or request.query_params.get("key") or ""
    if not hmac.compare_digest(key, settings.api_key):
        raise HTTPException(401, "missing or wrong API key (X-API-Key header or ?key=)")


def operator(request: Request):
    return (request.headers.get("x-operator") or "operator")[:60]


def range_file(path: Path, request: Request, media_type: str):
    """File response with HTTP Range support (browsers need it to seek in <video>)."""
    size = path.stat().st_size
    header = request.headers.get("range")
    base = {"Accept-Ranges": "bytes"}
    if not header:
        return FileResponse(path, media_type=media_type, headers=base)
    m = re.match(r"bytes=(\d*)-(\d*)$", header.strip())
    if not m or (not m.group(1) and not m.group(2)):
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    if m.group(1):
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else size - 1
    else:                                           # suffix range: last N bytes
        start, end = max(0, size - int(m.group(2))), size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    length = end - start + 1

    def chunks():
        with open(path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                data = f.read(min(1 << 20, left))
                if not data:
                    break
                left -= len(data)
                yield data

    return StreamingResponse(chunks(), status_code=206, media_type=media_type, headers={
        **base, "Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(length)})


def get_event(event_id):
    ev = state.manager.event_dict(event_id)
    if not ev:
        raise HTTPException(404, "event not found")
    return ev


def get_alert(alert_id):
    a = state.db.one("SELECT * FROM alerts WHERE id=?", (alert_id,))
    if not a:
        raise HTTPException(404, "alert not found")
    return a


def alert_view(a):
    a = dict(a)
    au = state.db.one("SELECT name, type, email FROM authorities WHERE id=?", (a["authority_id"],))
    a["authority"] = au
    return a


# ------------------------------------------------------------------ routers
public = APIRouter()
router = APIRouter(prefix="/api", dependencies=[Depends(require_key)])


@public.get("/api/health")
def health():
    return {"ok": True, "time": now_iso(), "send_mode": settings.send_mode,
            "test_recipient_set": bool(settings.test_recipient), "mock_detector": settings.mock_detector,
            "auth": bool(settings.api_key)}


# ---------------- cameras
@router.get("/cameras")
def list_cameras():
    cams = state.db.all("SELECT * FROM cameras ORDER BY id")
    return [{**c, "status": state.manager.status(c["id"])} for c in cams]


@router.post("/cameras", status_code=201)
def add_camera(body: CameraIn):
    cid = state.db.run(
        "INSERT INTO cameras(name, source, kind, lat, lng, road_type, enabled, loop, realtime, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (body.name, body.source, "stream", body.lat, body.lng, body.road_type, int(body.enabled),
         int(body.loop), int(body.realtime), now_iso()))
    if body.enabled:
        state.manager.start_camera(cid)
    return state.db.one("SELECT * FROM cameras WHERE id=?", (cid,))


@router.patch("/cameras/{cid}")
def patch_camera(cid: int, body: CameraPatch):
    if not state.db.one("SELECT id FROM cameras WHERE id=?", (cid,)):
        raise HTTPException(404, "camera not found")
    fields = {k: (int(v) if isinstance(v, bool) else v) for k, v in body.model_dump(exclude_unset=True).items()}
    state.db.update_fields("cameras", cid, **fields)
    return {**state.db.one("SELECT * FROM cameras WHERE id=?", (cid,)),
            "note": "restart the camera for source/loop/realtime changes to take effect"}


@router.delete("/cameras/{cid}", status_code=204)
def delete_camera(cid: int):
    state.manager.stop_camera(cid)
    for ev in state.db.all("SELECT clip_path, snapshot_path FROM events WHERE camera_id=?", (cid,)):
        for name, folder in ((ev["clip_path"], settings.clips_dir), (ev["snapshot_path"], settings.snap_dir)):
            if name:
                (folder / name).unlink(missing_ok=True)
    state.db.update("DELETE FROM cameras WHERE id=?", (cid,))
    state.manager.workers.pop(cid, None)


@router.post("/cameras/{cid}/start")
def start_camera(cid: int):
    if not state.db.one("SELECT id FROM cameras WHERE id=?", (cid,)):
        raise HTTPException(404, "camera not found")
    started = state.manager.start_camera(cid)
    state.db.update_fields("cameras", cid, enabled=1)
    return {"started": started, "status": state.manager.status(cid)}


@router.post("/cameras/{cid}/stop")
def stop_camera(cid: int):
    state.manager.stop_camera(cid)
    state.db.update_fields("cameras", cid, enabled=0)
    return {"status": state.manager.status(cid)}


@router.get("/cameras/{cid}/status")
def camera_status(cid: int):
    return state.manager.status(cid)


@router.get("/cameras/{cid}/stream")
async def camera_stream(cid: int, max_frames: Optional[int] = None):
    """Live preview as MJPEG: <img src="/api/cameras/1/stream?key=..."> works in any browser."""
    async def gen():
        last, sent = None, 0
        while True:
            jpg = state.manager.latest_jpeg(cid)
            if jpg is not None and jpg is not last:
                last = jpg
                sent += 1
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
                if max_frames and sent >= max_frames:
                    return
            st = state.manager.status(cid)
            if not st["running"] and (jpg is None or jpg is last):
                return
            await asyncio.sleep(0.1)
    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


# ---------------- uploads: analyse any video through the same detector
@router.post("/uploads", status_code=201)
async def upload_video(file: UploadFile = File(...), name: Optional[str] = Form(None),
                       lat: Optional[float] = Form(None), lng: Optional[float] = Form(None)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VID_EXT:
        raise HTTPException(400, f"unsupported file type '{ext}', use one of {VID_EXT}")
    dest = settings.uploads_dir / f"{uuid.uuid4().hex}{ext}"
    limit, size = settings.max_upload_mb * 1024 * 1024, 0
    with open(dest, "wb") as f:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"file larger than {settings.max_upload_mb} MB")
            f.write(chunk)
    cid = state.db.run(
        "INSERT INTO cameras(name, source, kind, lat, lng, road_type, enabled, loop, realtime, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (name or f"upload: {file.filename}", str(dest), "upload", lat, lng, "upload", 1, 0, 0, now_iso()))
    state.manager.start_camera(cid)
    return {"camera": state.db.one("SELECT * FROM cameras WHERE id=?", (cid,)),
            "hint": "poll GET /api/cameras/{id}/status until finished=true, then GET /api/events?camera_id={id}"}


# ---------------- events
@router.get("/events")
def list_events(camera_id: Optional[int] = None, label: Optional[str] = None,
                status: Optional[str] = Query(None, description="comma list, e.g. active,pending_review"),
                severity: Optional[str] = None, include_duplicates: bool = False,
                limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    where, args = [], []
    if camera_id is not None:
        where.append("e.camera_id=?"); args.append(camera_id)
    if label:
        where.append("e.label=?"); args.append(label)
    if status:
        sts = [s.strip() for s in status.split(",") if s.strip()]
        where.append(f"e.status IN ({','.join('?' * len(sts))})"); args += sts
    if severity:
        where.append("e.severity=?"); args.append(severity)
    if not include_duplicates:
        where.append("e.duplicate_of IS NULL")
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = state.db.one(f"SELECT COUNT(*) AS n FROM events e {w}", args)["n"]
    rows = state.db.all(
        f"SELECT e.*, c.name AS camera_name FROM events e JOIN cameras c ON c.id=e.camera_id {w} "
        f"ORDER BY e.id DESC LIMIT ? OFFSET ?", (*args, limit, offset))
    return {"total": total, "items": rows}


@router.get("/events/{eid}")
def event_detail(eid: int):
    ev = get_event(eid)
    cam = state.db.one("SELECT * FROM cameras WHERE id=?", (ev["camera_id"],))
    alerts = [alert_view(a) for a in state.db.all("SELECT * FROM alerts WHERE event_id=? ORDER BY id", (eid,))]
    return {**ev, "camera": cam, "alerts": alerts, "clip_ready": bool(ev["clip_path"])}


@router.get("/events/{eid}/clip")
def event_clip(eid: int, request: Request):
    ev = get_event(eid)
    if not ev["clip_path"] or not (settings.clips_dir / ev["clip_path"]).exists():
        raise HTTPException(404, "clip not ready yet")
    return range_file(settings.clips_dir / ev["clip_path"], request, "video/mp4")


@router.get("/events/{eid}/snapshot")
def event_snapshot(eid: int):
    ev = get_event(eid)
    if not ev["snapshot_path"] or not (settings.snap_dir / ev["snapshot_path"]).exists():
        raise HTTPException(404, "snapshot not available")
    return FileResponse(settings.snap_dir / ev["snapshot_path"], media_type="image/jpeg")


def _review(eid, request, status, note, reason=None):
    ev = get_event(eid)
    if ev["status"] == status:
        return ev
    if ev["status"] in ("confirmed", "dismissed"):
        raise HTTPException(409, f"event already {ev['status']}")
    state.db.update_fields("events", eid, status=status, reviewer=operator(request), review_note=note,
                           dismiss_reason=reason, reviewed_at=now_iso())
    state.manager.emit("updated", eid)
    return get_event(eid)


@router.post("/events/{eid}/confirm")
def confirm_event(eid: int, request: Request, body: ConfirmIn = ConfirmIn()):
    """Operator says: yes, this is real. Drafts emails to the nearest authorities (nothing is sent yet)."""
    ev = _review(eid, request, "confirmed", body.note)
    try:
        d = alert_svc.draft_alerts(state.db, eid)
        drafts = [alert_view(a) for a in d["created"]]
        problems, dup = d["problems"], d["duplicate_warning"]
    except alert_svc.AlertError as e:
        drafts, problems, dup = [], [str(e)], False
    return {"event": ev, "drafts": drafts, "problems": problems, "duplicate_warning": dup}


@router.post("/events/{eid}/dismiss")
def dismiss_event(eid: int, request: Request, body: DismissIn = DismissIn()):
    return _review(eid, request, "dismissed", body.note, body.reason)


@router.get("/events/{eid}/alerts")
def event_alerts(eid: int):
    get_event(eid)
    return [alert_view(a) for a in state.db.all("SELECT * FROM alerts WHERE event_id=? ORDER BY id", (eid,))]


@router.post("/events/{eid}/alerts/draft")
def draft(eid: int):
    get_event(eid)
    try:
        d = alert_svc.draft_alerts(state.db, eid)
    except alert_svc.AlertError as e:
        raise HTTPException(409, str(e))
    return {"drafts": [alert_view(a) for a in d["created"]], "problems": d["problems"]}


@router.post("/events/{eid}/alerts/send-all")
def send_all(eid: int):
    get_event(eid)
    out = []
    for a in state.db.all("SELECT id FROM alerts WHERE event_id=? AND status IN ('drafted','failed')", (eid,)):
        try:
            out.append(alert_view(alert_svc.send_alert(state.db, a["id"])))
        except alert_svc.AlertError as e:
            raise HTTPException(409, str(e))
    return {"sent": out, "mode": settings.send_mode}


@router.patch("/alerts/{aid}")
def edit_alert(aid: int, body: AlertPatch):
    a = get_alert(aid)
    if a["status"] != "drafted":
        raise HTTPException(409, "only drafted alerts can be edited")
    fields = body.model_dump(exclude_unset=True)
    state.db.update_fields("alerts", aid, **fields)
    return alert_view(get_alert(aid))


@router.post("/alerts/{aid}/send")
def send_one(aid: int):
    get_alert(aid)
    try:
        return {"alert": alert_view(alert_svc.send_alert(state.db, aid)), "mode": settings.send_mode}
    except alert_svc.AlertError as e:
        raise HTTPException(409, str(e))


@router.delete("/alerts/{aid}", status_code=204)
def delete_alert(aid: int):
    if get_alert(aid)["status"] != "drafted":
        raise HTTPException(409, "only drafted alerts can be deleted")
    state.db.update("DELETE FROM alerts WHERE id=?", (aid,))


# ---------------- authorities
@router.get("/authorities")
def list_authorities():
    return state.db.all("SELECT * FROM authorities ORDER BY type, name")


@router.post("/authorities", status_code=201)
def add_authority(body: AuthorityIn):
    aid = state.db.run("INSERT INTO authorities(name, type, lat, lng, email, phone, active) VALUES(?,?,?,?,?,?,?)",
                       (body.name, body.type, body.lat, body.lng, body.email, body.phone, int(body.active)))
    return state.db.one("SELECT * FROM authorities WHERE id=?", (aid,))


@router.patch("/authorities/{aid}")
def patch_authority(aid: int, body: AuthorityPatch):
    if not state.db.one("SELECT id FROM authorities WHERE id=?", (aid,)):
        raise HTTPException(404, "authority not found")
    fields = {k: (int(v) if isinstance(v, bool) else v) for k, v in body.model_dump(exclude_unset=True).items()}
    state.db.update_fields("authorities", aid, **fields)
    return state.db.one("SELECT * FROM authorities WHERE id=?", (aid,))


@router.delete("/authorities/{aid}", status_code=204)
def delete_authority(aid: int):
    if state.db.one("SELECT id FROM alerts WHERE authority_id=?", (aid,)):
        state.db.update_fields("authorities", aid, active=0)       # keep history, just deactivate
        return
    state.db.update("DELETE FROM authorities WHERE id=?", (aid,))


# ---------------- stats + training feedback
@router.get("/stats")
def stats():
    db = state.db
    by_label = db.all("SELECT label, COUNT(*) AS n FROM events WHERE duplicate_of IS NULL GROUP BY label")
    by_status = db.all("SELECT status, COUNT(*) AS n FROM events WHERE duplicate_of IS NULL GROUP BY status")
    conf = db.one("SELECT COUNT(*) AS n FROM events WHERE status='confirmed'")["n"]
    fa = db.one("SELECT COUNT(*) AS n FROM events WHERE status='dismissed' AND dismiss_reason='false_alarm'")["n"]
    return {
        "by_label": {r["label"]: r["n"] for r in by_label},
        "by_status": {r["status"]: r["n"] for r in by_status},
        "confirmed": conf, "false_alarms": fa,
        "operator_precision": round(conf / (conf + fa), 3) if conf + fa else None,
        "cameras_running": sum(1 for c in db.all("SELECT id FROM cameras") if state.manager.status(c["id"])["running"]),
        "alerts_sent": db.one("SELECT COUNT(*) AS n FROM alerts WHERE status IN ('sent','dry_run')")["n"],
    }


@router.post("/training/export")
def export_training():
    done = training.export_reviewed(state.db)
    return {"exported": done, "next": "python make_labels.py && python extract_features.py && python train.py"}


@router.post("/training/upload", status_code=201)
async def upload_training(file: UploadFile = File(...), label: str = Form(...)):
    from src.config import CLASSES
    if label not in CLASSES:
        raise HTTPException(400, f"label must be one of {CLASSES}")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VID_EXT:
        raise HTTPException(400, f"unsupported file type '{ext}'")
    folder = settings.train_videos_dir / label
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(file.filename).stem)[:60]
    dest = folder / f"up_{uuid.uuid4().hex[:6]}_{safe}{ext}"
    with open(dest, "wb") as f:
        while chunk := await file.read(1 << 20):
            f.write(chunk)
    return {"saved": str(dest), "next": "python make_labels.py && python extract_features.py && python train.py"}


# ------------------------------------------------------------------ public (signed links, no API key)
@public.get("/public/events/{eid}/clip")
def public_clip(eid: int, request: Request, t: str = ""):
    if not security.verify(t, eid, "clip"):
        raise HTTPException(403, "invalid or expired link")
    return event_clip(eid, request)


@public.get("/public/events/{eid}/snapshot")
def public_snapshot(eid: int, t: str = ""):
    if not security.verify(t, eid, "snapshot"):
        raise HTTPException(403, "invalid or expired link")
    return event_snapshot(eid)


@public.get("/public/ack/{token}", response_class=HTMLResponse)
def public_ack(token: str):
    a = alert_svc.ack(state.db, token)
    if not a:
        raise HTTPException(404, "unknown acknowledgement link")
    return ("<html><body style='font-family:sans-serif;max-width:480px;margin:60px auto'>"
            "<h2>Thank you - receipt acknowledged</h2><p>The control room has been notified that you "
            "received this alert.</p></body></html>")
