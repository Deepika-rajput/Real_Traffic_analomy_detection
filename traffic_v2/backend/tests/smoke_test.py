"""End-to-end smoke test with the MOCK detector (no torch/model needed).

    pip install httpx
    python backend/tests/smoke_test.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="traffic_test_"))
os.environ.update({
    "DATA_DIR": str(TMP / "data"), "TRAIN_VIDEOS_DIR": str(TMP / "videos"),
    "MOCK_DETECTOR": "1", "MOCK_SCRIPT": "accident:10-16,accident:17-22,congestion:40-48",
    "API_KEY": "secret", "SEND_MODE": "dry_run", "ACK_TIMEOUT_MIN": "0",
    "PUBLIC_BASE_URL": "http://test.local",
})

import cv2          # noqa: E402
import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import alerts as alert_svc  # noqa: E402
from backend.app.clips import ffmpeg_exe     # noqa: E402
from backend.app.main import app             # noqa: E402
from backend.app.state import state          # noqa: E402

H = {"X-API-Key": "secret", "X-Operator": "deepika"}


def make_video(path, secs=60, fps=10, size=(320, 180)):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    for i in range(secs * fps):
        f = np.full((size[1], size[0], 3), 90, np.uint8)
        x = (i * 3) % (size[0] - 40)
        cv2.rectangle(f, (x, 80), (x + 40, 110), (0, 0, 255), -1)
        cv2.putText(f, str(i // fps), (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        w.write(f)
    w.release()


def wait(cond, what, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = cond()
        if v:
            return v
        time.sleep(0.3)
    raise AssertionError(f"timeout waiting for {what}")


def upload(c, video, name, lat=None, lng=None):
    data = {"name": name}
    if lat is not None:
        data.update(lat=str(lat), lng=str(lng))
    with open(video, "rb") as f:
        r = c.post("/api/uploads", headers=H, data=data, files={"file": ("clip.mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text
    cid = r.json()["camera"]["id"]
    wait(lambda: c.get(f"/api/cameras/{cid}/status", headers=H).json()["finished"], "camera finished")
    evs = lambda: c.get("/api/events", headers=H, params={"camera_id": cid, "include_duplicates": True}).json()["items"]
    wait(lambda: evs() and all(e["clip_path"] for e in evs()), "clips transcoded")
    return cid, sorted(evs(), key=lambda e: e["id"])


def main():
    video = TMP / "synthetic.mp4"
    make_video(video)
    with TestClient(app) as c:
        # ---- health + auth
        assert c.get("/api/health").json()["ok"]
        assert c.get("/api/cameras").status_code == 401
        assert c.get("/api/cameras", headers=H).status_code == 200
        assert c.get("/api/cameras?key=secret").status_code == 200
        print("ok  health + API key")

        # ---- authorities
        def auth(name, typ, lat, lng):
            r = c.post("/api/authorities", headers=H, json={"name": name, "type": typ, "lat": lat, "lng": lng,
                                                            "email": f"{name.lower().replace(' ', '')}@example.test"})
            assert r.status_code == 201, r.text
            return r.json()["id"]
        near_police = auth("Near Police", "police", 10.01, 20.01)
        far_police = auth("Far Police", "police", 10.25, 20.25)          # ~39 km: inside MAX_RADIUS_KM=50
        remote_police = auth("Remote Police", "police", 10.40, 20.40)    # ~62 km: outside the radius, never used
        hospital = auth("City Hospital", "hospital", 10.02, 20.00)
        traffic = auth("Traffic Control", "traffic_control", 10.03, 20.03)
        assert c.post("/api/authorities", headers=H, json={"name": "x", "type": "police", "lat": 1, "lng": 1,
                                                           "email": "not-an-email"}).status_code == 422
        print("ok  authorities CRUD + validation")

        # ---- upload + detection + clips
        assert c.post("/api/uploads", headers=H, files={"file": ("a.txt", b"x", "text/plain")}).status_code == 400
        # websocket must receive live events
        with c.websocket_connect("/ws/events?key=secret") as ws:
            assert ws.receive_json()["type"] == "hello"
            cid, evs = upload(c, video, "cam A", 10.0, 20.0)
            msg = ws.receive_json()
            assert msg["type"] == "event" and msg["action"] in ("created", "updated")
        print("ok  websocket live events")
        assert len(evs) == 2, [(e["id"], e["label"], e["merged_count"]) for e in evs]
        acc, cong = evs[0], evs[1]
        assert acc["label"] == "accident" and acc["merged_count"] == 1, acc      # flapping alert merged
        assert cong["label"] == "congestion"
        assert acc["status"] == "pending_review" and acc["severity"] == "high"
        assert 6 < acc["clip_offset_s"] < 10 and 20 < acc["clip_duration_s"] < 35, acc
        print(f"ok  2 events (flap merged), clip {acc['clip_duration_s']}s with alert at {acc['clip_offset_s']}s")

        # ---- clip: H.264, Range support, snapshot
        r = c.get(f"/api/events/{acc['id']}/clip", headers=H)
        assert r.status_code == 200 and r.headers["content-type"] == "video/mp4" and r.headers["accept-ranges"] == "bytes"
        full = r.content
        r2 = c.get(f"/api/events/{acc['id']}/clip", headers={**H, "Range": "bytes=0-99"})
        assert r2.status_code == 206 and len(r2.content) == 100 and r2.headers["content-range"].startswith("bytes 0-99/")
        r3 = c.get(f"/api/events/{acc['id']}/clip", headers={**H, "Range": f"bytes={len(full)-50}-"})
        assert r3.status_code == 206 and r3.content == full[-50:]
        assert c.get(f"/api/events/{acc['id']}/clip", headers={**H, "Range": "bytes=999999999-"}).status_code == 416
        probe = TMP / "dl.mp4"
        probe.write_bytes(full)
        info = subprocess.run([ffmpeg_exe(), "-i", str(probe)], capture_output=True, text=True).stderr
        assert "h264" in info.lower(), info[-400:]
        snap = c.get(f"/api/events/{acc['id']}/snapshot", headers=H)
        assert snap.status_code == 200 and snap.content[:2] == b"\xff\xd8"
        print("ok  clip is H.264, Range requests (206/416), snapshot")

        # ---- MJPEG preview
        r = c.get(f"/api/cameras/{cid}/stream?max_frames=1", headers=H)
        assert r.status_code == 200 and b"\xff\xd8" in r.content and b"--frame" in r.content
        print("ok  MJPEG preview")

        # ---- alerts: gated until a human confirms
        assert c.post(f"/api/events/{acc['id']}/alerts/draft", headers=H).status_code == 409
        r = c.post(f"/api/events/{acc['id']}/confirm", headers=H, json={"note": "clearly a crash"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["event"]["status"] == "confirmed" and body["event"]["reviewer"] == "deepika"
        assert body["problems"] == []
        drafts = {d["authority"]["type"]: d for d in body["drafts"]}
        assert set(drafts) == {"police", "hospital"}, drafts.keys()
        assert drafts["police"]["authority_id"] == near_police            # nearest, not the far one
        txt = drafts["police"]["body"]
        assert "maps?q=10.000000,20.000000" in txt and "http://test.local/public/events/" in txt
        assert "deepika" in txt and "/public/ack/" in txt
        # idempotent
        assert c.post(f"/api/events/{acc['id']}/alerts/draft", headers=H).json()["drafts"] == []
        # edit a draft, then send everything (dry run => files in outbox, nothing really sent)
        aid = drafts["police"]["id"]
        assert c.patch(f"/api/alerts/{aid}", headers=H, json={"body": txt + "\nP.S. edited"}).status_code == 200
        sent = c.post(f"/api/events/{acc['id']}/alerts/send-all", headers=H).json()
        assert sent["mode"] == "dry_run" and {a["status"] for a in sent["sent"]} == {"dry_run"}
        eml = TMP / "data" / "outbox" / f"alert_{aid}.eml"
        assert eml.exists() and "P.S. edited" in eml.read_text()
        assert c.patch(f"/api/alerts/{aid}", headers=H, json={"body": "x"}).status_code == 409   # locked once sent
        print("ok  confirm -> nearest-authority drafts -> edit -> dry-run send (+ idempotent, locked)")

        # ---- signed public evidence links + ack
        import re
        m = re.search(r"/public/events/(\d+)/clip\?t=([\w\-\.]+)", txt)
        assert c.get(m.group(0)).status_code == 200                       # no API key needed
        assert c.get(f"/public/events/{acc['id']}/clip?t=bad").status_code == 403
        assert c.get(f"/public/events/{cong['id']}/clip?t={m.group(2)}").status_code == 403   # token is per event
        token = drafts["hospital"]["ack_token"]
        assert "acknowledged" in c.get(f"/public/ack/{token}").text.lower()
        print("ok  signed evidence links (tamper/other-event rejected) + ack")

        # ---- escalation: police never acked -> next nearest police gets it
        esc = alert_svc.escalate_overdue(state.db)
        assert len(esc) == 1 and esc[0]["authority_id"] == far_police and "ESCALATION" in esc[0]["body"], esc
        assert alert_svc.escalate_overdue(state.db) == []                  # not repeated, remote police (62 km) never used
        print("ok  escalation to next-nearest authority")

        # ---- camera without coordinates: confirm works, draft explains why not
        c.patch(f"/api/cameras/{cid}", headers=H, json={"lat": None})
        state.db.update("UPDATE cameras SET lat=NULL, lng=NULL WHERE id=?", (cid,))
        r = c.post(f"/api/events/{cong['id']}/confirm", headers=H).json()
        assert r["drafts"] == [] and "coordinates" in r["problems"][0]
        state.db.update("UPDATE cameras SET lat=10.0, lng=20.0 WHERE id=?", (cid,))
        r = c.post(f"/api/events/{cong['id']}/alerts/draft", headers=H).json()
        assert [d["authority"]["type"] for d in r["drafts"]] == ["traffic_control"]
        print("ok  missing-coordinates handled, congestion -> traffic control")

        # ---- dismiss + training feedback loop
        cid2, evs2 = upload(c, video, "cam B", 10.0, 20.0)
        fa = evs2[0]
        r = c.post(f"/api/events/{fa['id']}/dismiss", headers=H, json={"reason": "false_alarm"})
        assert r.json()["status"] == "dismissed"
        assert c.post(f"/api/events/{fa['id']}/confirm", headers=H).status_code == 409   # can't flip a decision
        ex = c.post("/api/training/export", headers=H).json()
        labels = sorted(x["label"] for x in ex["exported"])
        assert labels == ["accident", "congestion", "normal"], labels
        for x in ex["exported"]:
            assert Path(x["file"]).exists() and Path(x["file"]).stat().st_size > 1000
        assert c.post("/api/training/export", headers=H).json()["exported"] == []        # exported once
        print("ok  dismiss + export (confirmed -> trimmed class clip, false alarm -> normal)")

        # ---- stats, listing filters, camera lifecycle
        st = c.get("/api/stats", headers=H).json()
        assert st["confirmed"] == 2 and st["false_alarms"] == 1 and st["operator_precision"] == 0.667, st
        lst = c.get("/api/events", headers=H, params={"status": "pending_review,active"}).json()
        assert lst["total"] == len(lst["items"]) and all(e["status"] == "pending_review" for e in lst["items"])
        assert c.get("/api/events", headers=H, params={"label": "congestion"}).json()["total"] == 2
        assert c.post(f"/api/cameras/{cid2}/start", headers=H).status_code == 200
        n_before = len(list((TMP / "data" / "clips").glob("*.mp4")))
        assert c.delete(f"/api/cameras/{cid2}", headers=H).status_code == 204
        assert len(list((TMP / "data" / "clips").glob("*.mp4"))) < n_before
        assert c.get("/api/events/99999", headers=H).status_code == 404
        print("ok  stats, filters, camera delete cleans files")

        # ---- a real (looping) camera from a file path
        r = c.post("/api/cameras", headers=H, json={"name": "cam C", "source": str(video), "lat": 10, "lng": 20,
                                                    "enabled": False})
        assert r.status_code == 201
        print("ok  add camera by file path")
    print("\nALL BACKEND CHECKS PASSED")


if __name__ == "__main__":
    main()
