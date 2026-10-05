"""Single source of truth. Train and inference MUST share these values."""

IMG_SIZE = 224          # drop to 160 for ~2x faster CPU (then re-run extract_features.py)
CLIP_LEN = 16           # frames per clip
SAMPLE_FPS = 5.0        # frames per SECOND we look at (time-based, so any camera fps works)
                        # 16 frames @ 5 fps = 3.2 s of context. Raise CLIP_LEN or lower SAMPLE_FPS for more.
INFER_EVERY = 2         # run the transformer every N sampled frames (0.4 s at 5 fps)

# Per-frame feature = ResNet18 appearance (512)  +  optical-flow motion summary (15)
CNN_DIM = 512
MOTION_DIM = 15
FEAT_DIM = CNN_DIM + MOTION_DIM
MOTION_SIZE = 96        # frames are shrunk to 96x96 gray for optical flow (cheap on CPU)
FEATURE_VERSION = 2     # bump to invalidate cached features after changing feature code

# index 0 must stay "normal". Add/rename classes here, then use the same names as folder names.
CLASSES = ["normal", "accident", "sudden_stop", "congestion"]
NORMAL = 0
ANOMALIES = [c for c in CLASSES if c != "normal"]

# alert rule per class: (hits needed, out of last N transformer predictions)
# Congestion clips in many datasets are only 7-20 s, so keep it equal to the others while testing;
# raise to e.g. (6, 8) in production if you want congestion alerts to need longer persistence.
ALERT_RULE = {"accident": (4, 6), "sudden_stop": (4, 6), "congestion": (4, 6)}
PRIORITY = ["accident", "sudden_stop", "congestion"]   # which alert wins if several fire


def stride_for(video_fps):
    """Read every Nth frame so we get ~SAMPLE_FPS frames per second."""
    return max(1, round((video_fps or 25.0) / SAMPLE_FPS))