"""Torch-free video sampling shared by training-time extraction."""
import cv2
import numpy as np

from .config import IMG_SIZE, stride_for
from .motion import gray_small, motion_features


def video_info(path):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return fps, n, (n / fps if n > 0 else 0.0)


def sample_segment(path, start, end, phase=0, flip=False):
    """Yield (rgb224 uint8, motion15 float32) for ~SAMPLE_FPS frames/sec in [start, end).

    phase shifts which frames get sampled (free augmentation); flip mirrors the image
    (motion is computed on the mirrored frames, so it stays consistent).
    """
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    stride = stride_for(fps)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    first = int(start * fps) + phase
    last = (total if total > 0 else 10 ** 12) if end is None else int(end * fps)
    if total > 0:
        last = min(last, total)
    cap.set(cv2.CAP_PROP_POS_FRAMES, first)

    prev, i = None, first
    while i < last:
        if (i - first) % stride:
            ok = cap.grab()                      # skip decoding unsampled frames
        else:
            ok, frame = cap.read()
            if ok:
                rgb = cv2.cvtColor(cv2.resize(frame, (IMG_SIZE, IMG_SIZE)), cv2.COLOR_BGR2RGB)
                if flip:
                    rgb = np.ascontiguousarray(rgb[:, ::-1])
                gray = gray_small(rgb)
                yield rgb, motion_features(prev, gray)
                prev = gray
        if not ok:
            break
        i += 1
    cap.release()
