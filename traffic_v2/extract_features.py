"""Video -> cached per-frame features (CNN appearance + optical-flow motion).

    python extract_features.py

* Reads labels.csv (made by make_labels.py).
* Every (video, time range, sampling phase, flip) is cached in features/cache/ - adding new
  videos later only processes the NEW ones. Changing IMG_SIZE / SAMPLE_FPS / FEATURE_VERSION
  or replacing a video file automatically invalidates its cache.
* Train anomaly segments get extra sampling phases + flipped copies (free augmentation).
"""
import argparse
import hashlib
import os
import time

import numpy as np
import torch

from src.config import (CLASSES, CLIP_LEN, FEAT_DIM, FEATURE_VERSION, IMG_SIZE, NORMAL,
                        SAMPLE_FPS)
from src.labels import SPLITS, check_overlaps, read_rows
from src.model import FrameEncoder
from src.video_io import sample_segment


@torch.inference_mode()
def encode_batch(encoder, frames_rgb):
    x = torch.from_numpy(np.stack(frames_rgb)).permute(0, 3, 1, 2).float() / 255.0
    return encoder(x)


def segment_features(encoder, path, start, end, phase=0, flip=False):
    cnn, mot, batch = [], [], []
    for rgb, m in sample_segment(path, start, end, phase, flip):
        batch.append(rgb)
        mot.append(m)
        if len(batch) == 32:
            cnn.append(encode_batch(encoder, batch))
            batch = []
        if len(mot) % 1000 == 0:
            print(f"      {len(mot)} frames...", flush=True)
    if batch:
        cnn.append(encode_batch(encoder, batch))
    if not mot:
        return torch.zeros(0, FEAT_DIM)
    m = torch.from_numpy(np.stack(mot))
    if len(m) > 1:
        m[0] = m[1]                      # first frame has no previous frame -> copy
    return torch.cat([torch.cat(cnn), m], dim=1)


def cache_file(out, r, phase, flip):
    st = os.stat(r["video"])
    key = "|".join(map(str, [os.path.abspath(r["video"]), st.st_size, st.st_mtime_ns, r["start"],
                             r["end"], phase, flip, IMG_SIZE, SAMPLE_FPS, FEATURE_VERSION]))
    return os.path.join(out, "cache", hashlib.md5(key.encode()).hexdigest() + ".pt")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="labels.csv")
    ap.add_argument("--out", default="features")
    ap.add_argument("--anomaly-phases", type=int, default=4,
                    help="train anomaly segments are sampled at this many frame offsets")
    ap.add_argument("--no-flip", action="store_true", help="no mirrored copies of train anomalies")
    args = ap.parse_args()

    rows = read_rows(args.labels, CLASSES)
    if not rows:
        raise SystemExit("labels.csv is empty. Put videos in videos/<class>/ and run make_labels.py")
    for r in rows:
        if not os.path.exists(r["video"]):
            raise SystemExit(f"video not found: {r['video']}")
    check_overlaps(rows)
    os.makedirs(os.path.join(args.out, "cache"), exist_ok=True)

    torch.set_num_threads(os.cpu_count() or 4)
    enc = None
    out = {s: {"seqs": [], "labels": [], "names": []} for s in SPLITS}
    t0, new, cached = time.time(), 0, 0
    for n, r in enumerate(rows, 1):
        anomaly_train = r["split"] == "train" and r["label"] != CLASSES[NORMAL]
        phases = range(args.anomaly_phases) if anomaly_train else [0]
        flips = [False, True] if (anomaly_train and not args.no_flip) else [False]
        end_txt = "end" if r["end"] is None else f"{r['end']:g}"
        print(f"[{n}/{len(rows)}] {r['video']} {r['start']:g}-{end_txt}s  {r['split']}/{r['label']}")
        for p in phases:
            for fl in flips:
                cf = cache_file(args.out, r, p, fl)
                if os.path.exists(cf):
                    f = torch.load(cf)
                    cached += 1
                else:
                    if enc is None:
                        enc = FrameEncoder()
                    f = segment_features(enc, r["video"], r["start"], r["end"], phase=p, flip=fl)
                    torch.save(f, cf)
                    new += 1
                if len(f) < CLIP_LEN:
                    print(f"   ! too short (<{CLIP_LEN} sampled frames), skipped")
                    continue
                name = f"{os.path.basename(r['video'])}@{r['start']:g}-{end_txt}|p{p}{'f' if fl else ''}"
                out[r["split"]]["seqs"].append(f)
                out[r["split"]]["labels"].append(CLASSES.index(r["label"]))
                out[r["split"]]["names"].append(name)
        print(f"   ok ({time.time() - t0:.0f}s elapsed)")

    print(f"\nfeature sets: {new} computed, {cached} loaded from cache")
    for s in SPLITS:
        d = out[s]
        if not d["seqs"]:
            print(f"{s}: no data")
            continue
        torch.save(d, os.path.join(args.out, f"{s}.pt"))
        secs = {c: 0.0 for c in CLASSES}
        for f, y in zip(d["seqs"], d["labels"]):
            secs[CLASSES[y]] += len(f) / SAMPLE_FPS
        print(f"{s}: " + ", ".join(f"{c} {v:.0f}s" for c, v in secs.items() if v))
