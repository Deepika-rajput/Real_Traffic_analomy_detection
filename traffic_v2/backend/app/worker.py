"""Camera workers (one thread per camera/upload) and the Manager that ties DB, workers and websockets."""
import asyncio
import threading
import time
from pathlib import Path

import cv2

from . import detectors
from .clips import ClipRecorder
from .config import settings
from .db import now_iso


def severity_for(label, peak, duration_s):
    peak = peak or 0.0
    if peak >= settings.high_prob and (label != "congestion" or (duration_s or 0) >= 20):
        return "high"
    if peak >= settings.med_prob:
        return "medium"
    return "low"


def parse_source(src):
    s = str(src).strip()
    return int(s) if s.isdigit() else s


def is_live(src):
    return isinstance(src, int) or "://" in str(src)


class Manager:
    def __init__(self, db):
        self.db = db
        self.workers = {}
        self.lock = threading.Lock()
        self.loop = None                 # asyncio loop, set at startup (for websocket broadcasts)
        self.clients = set()             # connected websockets

    # ---------- websocket fan-out (called from worker threads) ----------
    def broadcast(self, message):
        if not self.loop or not self.clients:
            return
        asyncio.run_coroutine_threadsafe(self._send_all(message), self.loop)

    async def _send_all(self, message):
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    # ---------- worker lifecycle ----------
    def start_camera(self, camera_id):
        with self.lock:
            w = self.workers.get(camera_id)
            if w and w.is_alive():
                return False
            cam = self.db.one("SELECT * FROM cameras WHERE id=?", (camera_id,))
            if not cam:
                raise KeyError(camera_id)
            w = CameraWorker(cam, self)
            self.workers[camera_id] = w
            w.start()
            return True

    def stop_camera(self, camera_id, wait=5.0):
        w = self.workers.get(camera_id)
        if not w:
            return False
        w.stop_event.set()
        w.join(timeout=wait)
        return True

    def status(self, camera_id):
        w = self.workers.get(camera_id)
        if not w:
            return {"running": False, "state": "STOPPED"}
        return w.snapshot()

    def stop_all(self):
        for w in list(self.workers.values()):
            w.stop_event.set()
        for w in list(self.workers.values()):
            w.join(timeout=5)

    def latest_jpeg(self, camera_id):
        w = self.workers.get(camera_id)
        return w.latest_jpeg if w else None

    # ---------- event bookkeeping ----------
    def event_dict(self, event_id):
        return self.db.one("SELECT e.*, c.name AS camera_name FROM events e JOIN cameras c "
                           "ON c.id=e.camera_id WHERE e.id=?", (event_id,))

    def emit(self, action, event_id):
        ev = self.event_dict(event_id)
        if ev:
            self.broadcast({"type": "event", "action": action, "event": ev})

    def clip_done(self, event_id, filename, duration, offset):
        self.db.update_fields("events", event_id, clip_path=filename, clip_duration_s=round(duration, 2),
                              clip_offset_s=round(offset, 2))
        self.emit("updated", event_id)


class CameraWorker(threading.Thread):
    def __init__(self, camera, manager):
        super().__init__(daemon=True, name=f"camera-{camera['id']}")
        self.cam, self.m, self.db = camera, manager, manager.db
        self.stop_event = threading.Event()
        self.latest_jpeg = None
        self.recorder = ClipRecorder(camera["id"], manager.clip_done)
        self.cur = None            # {"id","label","peak"} while an alert is active
        self.last_end = None       # {"id","label","ts"} of the previous alert
        self.info = {"running": True, "state": "STARTING", "label": None, "probs": {}, "fps": 0.0,
                     "frames": 0, "error": None, "finished": False}

    def snapshot(self):
        return {**self.info, "running": self.is_alive() and not self.info["finished"]}

    # ---------- main loop ----------
    def run(self):
        cid = self.cam["id"]
        try:
            det = detectors.make_detector()
            src = parse_source(self.cam["source"])
            if not is_live(src) and not Path(str(src)).exists():
                raise RuntimeError(f"video file not found: {src}")
            cap = cv2.VideoCapture(src)
            if not cap.isOpened():
                raise RuntimeError(f"cannot open source: {src}")
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            det.set_fps(fps)
            pace = bool(self.cam["realtime"]) and not is_live(src)
            stream_every = max(1, round(fps / 8))
            idx, t_start, next_t = 0, time.perf_counter(), time.perf_counter()
            while not self.stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    if self.cam["loop"] and not is_live(src):
                        self._finish_active(idx / fps)
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        det.reset()
                        continue
                    break
                idx += 1
                ts = idx / fps
                res = det.process(frame)
                self.recorder.push(ts, frame)

                if res["event"]:
                    self._on_event(res["event"], ts, frame)
                if self.cur and res["probs"]:
                    self.cur["peak"] = max(self.cur["peak"], res["probs"].get(self.cur["label"], 0.0))

                self.info.update(state=res["state"], label=res["label"], probs=res["probs"], frames=idx,
                                 fps=round(idx / max(1e-6, time.perf_counter() - t_start), 1))
                if idx % stream_every == 0:
                    self._update_preview(frame, res)
                if pace:
                    next_t += 1.0 / fps
                    delay = next_t - time.perf_counter()
                    if delay > 0:
                        time.sleep(delay)
                    else:
                        next_t = time.perf_counter()      # fell behind: don't try to catch up
            self._finish_active(idx / fps)
            self.recorder.close_now()
            cap.release()
        except Exception as e:                            # noqa: BLE001
            self.info["error"] = f"{type(e).__name__}: {e}"
            try:
                self._finish_active(0)
                self.recorder.close_now()
            except Exception:
                pass
        finally:
            self.info.update(finished=True, state="FINISHED" if not self.info["error"] else "ERROR")

    # ---------- events ----------
    def _on_event(self, ev, ts, frame):
        if ev["type"] == "start":
            self._start_event(ev, ts, frame)
        elif ev["type"] == "end":
            self._end_event(ts)

    def _start_event(self, ev, ts, frame):
        label, prob = ev["label"], ev["prob"]
        le = self.last_end
        # Alert flapped off and on again while the clip is still recording -> same event.
        if le and le["label"] == label and self.recorder.is_recording and self.recorder.session.event_id == le["id"]:
            self.recorder.cancel_stop()
            row = self.db.one("SELECT merged_count FROM events WHERE id=?", (le["id"],))
            self.db.update_fields("events", le["id"], status="active", ended_at=None, video_t_end=None,
                                  merged_count=row["merged_count"] + 1)
            self.cur = {"id": le["id"], "label": label, "peak": prob}
            self.m.emit("updated", le["id"])
            return
        dup = None
        if le and le["label"] == label and ts - le["ts"] <= settings.cooldown_s:
            dup = le["id"]                                # repeat of a recent alert: flagged, not hidden
        eid = self.db.run(
            "INSERT INTO events(camera_id, label, status, severity, started_at, video_t_start, peak_prob, "
            "duplicate_of) VALUES(?,?,?,?,?,?,?,?)",
            (self.cam["id"], label, "active", severity_for(label, prob, 0), now_iso(), round(ts, 2), prob, dup))
        snap = f"event_{eid}.jpg"
        h, w = frame.shape[:2]
        shot = frame if w <= 1280 else cv2.resize(frame, (1280, int(h * 1280 / w)))
        cv2.imwrite(str(settings.snap_dir / snap), shot, [cv2.IMWRITE_JPEG_QUALITY, 88])
        self.db.update_fields("events", eid, snapshot_path=snap)
        self.recorder.begin(eid)
        self.cur = {"id": eid, "label": label, "peak": prob}
        self.m.emit("created", eid)

    def _end_event(self, ts):
        if not self.cur:
            return
        cur, self.cur = self.cur, None
        self.recorder.schedule_stop(ts)
        row = self.db.one("SELECT status, video_t_start FROM events WHERE id=?", (cur["id"],))
        dur = ts - (row["video_t_start"] or ts)
        fields = dict(ended_at=now_iso(), video_t_end=round(ts, 2), peak_prob=round(cur["peak"], 4),
                      severity=severity_for(cur["label"], cur["peak"], dur))
        if row["status"] == "active":
            fields["status"] = "pending_review"
        self.db.update_fields("events", cur["id"], **fields)
        self.last_end = {"id": cur["id"], "label": cur["label"], "ts": ts}
        self.m.emit("updated", cur["id"])

    def _finish_active(self, ts):
        if self.cur:
            self._end_event(ts)

    # ---------- live preview ----------
    def _update_preview(self, frame, res):
        h, w = frame.shape[:2]
        img = frame if w <= 640 else cv2.resize(frame, (640, int(h * 640 / w)))
        color = (0, 200, 0) if res["state"] in ("NORMAL", "LOADING") else (0, 0, 255)
        cv2.putText(img, res["state"], (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            self.latest_jpeg = buf.tobytes()
