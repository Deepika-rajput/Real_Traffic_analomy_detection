"""Record the video around an event: N seconds BEFORE the alert (from a ring buffer) + until
the event ends + a few seconds after. Output is H.264 so browsers can play it."""
import shutil
import subprocess
import threading
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from .config import settings


def ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def transcode_h264(src, dst):
    """mp4v (OpenCV) -> H.264 + faststart. Returns True if transcoded, else falls back to a rename."""
    exe = ffmpeg_exe()
    if exe:
        cmd = [exe, "-y", "-loglevel", "error", "-i", str(src), "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)]
        try:
            if subprocess.run(cmd, capture_output=True, timeout=600).returncode == 0 and Path(dst).exists():
                Path(src).unlink(missing_ok=True)
                return True
        except Exception:
            pass
    Path(src).replace(dst)      # no ffmpeg: file works in VLC but maybe not in browsers
    return False


class _Session:
    def __init__(self, event_id, writer, written, offset_s):
        self.event_id, self.writer = event_id, writer
        self.frames_written, self.offset_s = written, offset_s
        self.stop_at = None


class ClipRecorder:
    """One per camera. push() every frame; begin()/schedule_stop() around events."""

    def __init__(self, camera_id, on_done):
        self.camera_id, self.on_done = camera_id, on_done
        self.interval = 1.0 / settings.clip_fps
        self.ring = deque(maxlen=max(1, int(settings.pre_roll_s * settings.clip_fps)))
        self.max_frames = int(settings.max_clip_s * settings.clip_fps)
        self.last_push = -1e9
        self.session = None
        self.last_small = None

    # ---- helpers
    def _shrink(self, frame):
        h, w = frame.shape[:2]
        if w > settings.clip_max_width:
            s = settings.clip_max_width / w
            frame = cv2.resize(frame, (settings.clip_max_width, int(h * s)), interpolation=cv2.INTER_AREA)
        return frame

    @property
    def is_recording(self):
        return self.session is not None

    # ---- main API
    def push(self, ts, frame):
        if ts - self.last_push < self.interval - 1e-6:
            return
        self.last_push = ts
        small = self._shrink(frame)
        self.last_small = small
        s = self.session
        if s:
            if s.frames_written < self.max_frames:
                s.writer.write(small)
                s.frames_written += 1
            if s.stop_at is not None and ts >= s.stop_at:
                self._close()
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            self.ring.append(buf.tobytes())

    def begin(self, event_id):
        """Start a clip for this event, pre-filled with the ring buffer (frames before the alert)."""
        if self.session or self.last_small is None:
            return
        h, w = self.last_small.shape[:2]
        raw = settings.clips_dir / f"event_{event_id}_raw.mp4"
        writer = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"mp4v"), settings.clip_fps, (w, h))
        n = 0
        for b in list(self.ring):
            img = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
            if img is not None and img.shape[:2] == (h, w):
                writer.write(img)
                n += 1
        self.session = _Session(event_id, writer, n, n / settings.clip_fps)

    def schedule_stop(self, ts_end):
        if self.session:
            self.session.stop_at = ts_end + settings.post_roll_s

    def cancel_stop(self):
        """Event came back within the post-roll: keep recording the same clip."""
        if self.session:
            self.session.stop_at = None

    def close_now(self):
        if self.session:
            self._close()

    # ---- finishing
    def _close(self):
        s, self.session = self.session, None
        s.writer.release()
        raw = settings.clips_dir / f"event_{s.event_id}_raw.mp4"
        final = settings.clips_dir / f"event_{s.event_id}.mp4"
        duration = s.frames_written / settings.clip_fps

        def work():
            transcode_h264(raw, final)
            self.on_done(s.event_id, final.name, duration, s.offset_s)

        threading.Thread(target=work, daemon=True).start()


def trim_clip(src, dst, start_s, end_s=None):
    """Re-encode a time range of a clip (used when exporting confirmed events as training data)."""
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or settings.clip_fps
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    first = int(max(0.0, start_s) * fps)
    last = int(end_s * fps) if end_s else 10 ** 9
    cap.set(cv2.CAP_PROP_POS_FRAMES, first)
    out = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    i, n = first, 0
    while i < last:
        ok, f = cap.read()
        if not ok:
            break
        out.write(f)
        n += 1
        i += 1
    cap.release()
    out.release()
    return n / fps
