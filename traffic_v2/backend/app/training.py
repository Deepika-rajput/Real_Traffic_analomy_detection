"""Feedback loop: operator decisions become training data for the next model."""
import shutil

from .clips import trim_clip
from .config import settings

PRE_EVENT_MARGIN_S = 6.0     # alerts fire ~4 s after the event starts, so start the clip a bit earlier


def export_reviewed(db):
    """Confirmed events -> videos/<label>/ (trimmed to the event). False alarms -> videos/normal/
    (hard negatives: normal traffic the model got wrong). Then run make_labels.py + extract + train."""
    rows = db.all(
        "SELECT * FROM events WHERE exported=0 AND clip_path IS NOT NULL AND "
        "(status='confirmed' OR (status='dismissed' AND dismiss_reason='false_alarm'))")
    out = []
    for ev in rows:
        src = settings.clips_dir / ev["clip_path"]
        if not src.exists():
            continue
        label = ev["label"] if ev["status"] == "confirmed" else "normal"
        folder = settings.train_videos_dir / label
        folder.mkdir(parents=True, exist_ok=True)
        dst = folder / f"ev{ev['id']}_cam{ev['camera_id']}.mp4"
        if ev["status"] == "confirmed":
            trim_clip(src, dst, (ev["clip_offset_s"] or 0) - PRE_EVENT_MARGIN_S)
        else:
            shutil.copy(src, dst)
        db.update_fields("events", ev["id"], exported=1)
        out.append({"event_id": ev["id"], "label": label, "file": str(dst)})
    return out
