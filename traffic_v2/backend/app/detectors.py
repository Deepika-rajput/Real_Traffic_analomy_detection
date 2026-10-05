"""Detector factory. Real = src.detector.StreamDetector. Mock = scripted fake for UI work / tests."""
import os
import sys
from pathlib import Path

from .config import PROJECT_ROOT, settings

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import CLASSES  # noqa: E402  (torch-free)


def parse_script(script):
    """'accident:5-10,congestion:20-30' -> [(label, 5.0, 10.0), ...]  (video seconds)"""
    segs = []
    for part in script.split(","):
        part = part.strip()
        if not part:
            continue
        label, rng = part.split(":")
        a, b = rng.split("-")
        segs.append((label.strip(), float(a), float(b)))
    return segs


class MockDetector:
    """Same interface as StreamDetector, but raises scripted alerts at fixed video times."""

    def __init__(self, script):
        self.segs = parse_script(script)
        self.fps = 25.0
        self.reset()

    def set_fps(self, fps):
        self.fps = fps or 25.0
        self.reset()

    def reset(self):
        self.i = 0
        self.active = None

    def process(self, frame_bgr):
        self.i += 1
        t = self.i / self.fps
        cur = next((l for l, a, b in self.segs if a <= t < b), None)
        event = None
        if cur and cur != self.active:
            event = {"type": "start", "label": cur, "prob": 0.95, "frame": self.i}
        elif not cur and self.active:
            event = {"type": "end", "label": self.active, "prob": 0.95, "frame": self.i}
        self.active = cur
        probs = {c: 0.02 for c in CLASSES}
        probs[cur or "normal"] = 0.95
        return {"state": cur.upper() if cur else "NORMAL", "label": cur, "p_top": 0.95,
                "probs": probs, "event": event}


def make_detector():
    """Called once per camera worker. Raises RuntimeError with a readable message if impossible."""
    if settings.mock_detector:
        return MockDetector(settings.mock_script)
    if not Path(settings.weights).exists():
        raise RuntimeError(f"model weights not found: {settings.weights}. "
                           f"Run train.py first, or start the server with MOCK_DETECTOR=1 for UI work.")
    from src.detector import StreamDetector      # imports torch, only when really needed
    return StreamDetector(settings.weights)
