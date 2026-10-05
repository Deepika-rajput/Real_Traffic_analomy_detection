import math
import os
from collections import deque

import cv2
import torch

from .config import (ALERT_RULE, ANOMALIES, CLASSES, CLIP_LEN, IMG_SIZE, INFER_EVERY,
                     PRIORITY, stride_for)
from .model import AccidentTransformer
from .motion import gray_small, motion_features


class StreamDetector:
    """Feed frames one by one (any camera fps); get back the current traffic state.

    - Samples ~SAMPLE_FPS frames/second (stride computed from `fps`).
    - Per sampled frame: ResNet appearance (once) + optical-flow motion -> ring buffer of CLIP_LEN.
    - Transformer runs every INFER_EVERY sampled frames.
    - Each anomaly class has its own threshold and k-of-N persistence rule,
      so one noisy window never raises an alert.

    process() returns:
      state : LOADING | NORMAL | WARNING | ACCIDENT | SUDDEN_STOP | CONGESTION
      label : the anomaly class behind state (None when NORMAL)
      probs : {class: probability} from the latest prediction
      event : None, or {"type": "start"|"end", "label": ..., "prob": ..., "frame": n}
              exactly once when an alert begins / ends  <- the FastAPI worker consumes this
    """

    def __init__(self, weights="temporal.pth", fps=25.0):
        torch.set_num_threads(os.cpu_count() or 4)
        ckpt = torch.load(weights, map_location="cpu")
        if ckpt["classes"] != CLASSES:
            raise ValueError(f"checkpoint classes {ckpt['classes']} != config.CLASSES {CLASSES}")
        self.model = AccidentTransformer()
        self.model.temporal.load_state_dict(ckpt["state"])
        self.model.eval()
        self.thr = ckpt["thresholds"]
        self.stride = stride_for(fps)
        self.reset()

    def set_fps(self, fps):
        """Call when switching to a video/camera with a different frame rate (also resets state)."""
        self.stride = stride_for(fps)
        self.reset()

    def reset(self):
        self.feats = deque(maxlen=CLIP_LEN)
        self.hits = {c: deque(maxlen=ALERT_RULE[c][1]) for c in ANOMALIES}
        self.prev_gray = None
        self.frame_i = 0
        self.sampled = 0
        self.active = None                      # anomaly class currently alerting
        self.last = {"state": "LOADING", "label": None, "p_top": 0.0,
                     "probs": {c: 0.0 for c in CLASSES}}

    @torch.inference_mode()
    def process(self, frame_bgr):
        self.frame_i += 1
        if (self.frame_i - 1) % self.stride:
            return {**self.last, "event": None}           # unsampled frame: reuse last result

        rgb = cv2.cvtColor(cv2.resize(frame_bgr, (IMG_SIZE, IMG_SIZE)), cv2.COLOR_BGR2RGB)
        x = torch.from_numpy(rgb).permute(2, 0, 1).float().div(255.0).unsqueeze(0)
        gray = gray_small(rgb)
        mot = torch.from_numpy(motion_features(self.prev_gray, gray))
        self.prev_gray = gray
        self.feats.append(torch.cat([self.model.encode(x)[0], mot]))   # appearance + motion
        self.sampled += 1

        event = None
        if len(self.feats) < CLIP_LEN:
            self.last = {**self.last, "state": "LOADING"}
        elif self.sampled % INFER_EVERY == 0:
            seq = torch.stack(list(self.feats)).unsqueeze(0)           # (1, T, 527)
            p = torch.softmax(self.model.temporal(seq), 1)[0]
            probs = {c: p[i].item() for i, c in enumerate(CLASSES)}
            for c in ANOMALIES:
                self.hits[c].append(probs[c] >= self.thr.get(c, 0.9))

            state, label = "NORMAL", None
            for c in PRIORITY:                                         # full alert
                if sum(self.hits[c]) >= ALERT_RULE[c][0]:
                    state, label = c.upper(), c
                    break
            else:                                                      # halfway there -> warning
                for c in PRIORITY:
                    if sum(self.hits[c]) >= math.ceil(ALERT_RULE[c][0] / 2):
                        state, label = "WARNING", c
                        break

            alert = label if state not in ("NORMAL", "WARNING") else None
            if alert and alert != self.active:
                event = {"type": "start", "label": alert, "prob": probs[alert], "frame": self.frame_i}
            elif self.active and state == "NORMAL":
                event = {"type": "end", "label": self.active, "prob": probs[self.active], "frame": self.frame_i}
            if alert or state == "NORMAL":
                self.active = alert

            top = label or max(ANOMALIES, key=lambda c: probs[c])
            self.last = {"state": state, "label": label, "p_top": probs[top], "probs": probs}
        return {**self.last, "event": event}
