"""Cheap motion descriptor from two consecutive sampled frames (optical flow, CPU-friendly).

Why: a still frame can't tell 'dense but flowing' from 'dense and stopped'. Flow can.
Output (15 values, log-scaled so level information survives):
  12 = mean flow magnitude in a 3x4 grid, 3 = global mean / std / fraction of moving pixels.
Magnitude is expressed as % of image width per sampling interval, so it is roughly
resolution independent.
"""
import cv2
import numpy as np

from .config import MOTION_DIM, MOTION_SIZE

GRID = (3, 4)


def gray_small(rgb):
    """rgb: (H,W,3) uint8 -> (MOTION_SIZE, MOTION_SIZE) uint8 gray."""
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return cv2.resize(g, (MOTION_SIZE, MOTION_SIZE), interpolation=cv2.INTER_AREA)


def motion_features(prev_gray, gray):
    if prev_gray is None:
        return np.zeros(MOTION_DIM, np.float32)
    flow = cv2.calcOpticalFlowFarneback(prev_gray, gray, None, 0.5, 2, 9, 2, 5, 1.1, 0)
    mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2) * (100.0 / MOTION_SIZE)
    gh, gw = GRID
    cells = mag.reshape(gh, MOTION_SIZE // gh, gw, MOTION_SIZE // gw).mean(axis=(1, 3)).ravel()
    glob = np.array([mag.mean(), mag.std(), (mag > 0.5).mean()])
    v = np.log1p(np.concatenate([cells, glob])).astype(np.float32)
    assert v.shape[0] == MOTION_DIM
    return v
