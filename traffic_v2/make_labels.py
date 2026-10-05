"""Scan videos/<class>/ and add any NEW video to labels.csv (existing rows are never touched).

    videos/normal/*.mp4   videos/accident/*.mp4   videos/sudden_stop/*.mp4   videos/congestion/*.mp4

    python make_labels.py

Each new video is labeled as its folder's class for its WHOLE length and assigned to
train/val/test automatically (balanced per class, ~70/15/15 by duration, and existing
assignments never change when you add more videos).
Videos longer than --long-min minutes are cut by TIME into train/val/test pieces instead.

Whole-video labels are only right if the whole video really is that state:
trim/edit start_s,end_s in labels.csv for accident clips with long normal lead-in, or
for videos that mix states (add several rows for the same video with different ranges).
"""
import argparse
import os

from src.config import CLASSES
from src.labels import SPLITS, append_rows, check_overlaps, read_rows
from src.video_io import video_info

VID_EXT = (".mp4", ".avi", ".mov", ".mkv", ".m4v", ".webm")
TARGET = {"train": 0.70, "val": 0.15, "test": 0.15}

ap = argparse.ArgumentParser()
ap.add_argument("--root", default="videos")
ap.add_argument("--labels", default="labels.csv")
ap.add_argument("--long-min", type=float, default=10.0)
args = ap.parse_args()

rows = read_rows(args.labels, CLASSES)
known = {os.path.normcase(r["video"]) for r in rows}
dur_cache = {}


def dur(path):
    if path not in dur_cache:
        dur_cache[path] = video_info(path)[2]
    return dur_cache[path]


# seconds already assigned per class/split
secs = {c: {s: 0.0 for s in SPLITS} for c in CLASSES}
for r in rows:
    if os.path.exists(r["video"]):
        end = dur(r["video"]) if r["end"] is None else r["end"]
        secs[r["label"]][r["split"]] += max(0.0, end - r["start"])

new_rows = []
for cls in CLASSES:
    folder = os.path.join(args.root, cls)
    if not os.path.isdir(folder):
        continue
    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith(VID_EXT):
            continue
        path = os.path.normpath(os.path.join(folder, f))
        if os.path.normcase(path) in known:
            continue
        D = dur(path)
        if D <= 0:
            print(f"  ! cannot read {path}, skipped")
            continue
        if D > args.long_min * 60:
            a, b = D * TARGET["train"], D * (TARGET["train"] + TARGET["val"])
            parts = [("train", 0.0, a), ("val", a, b), ("test", b, None)]
            for s, st, en in parts:
                new_rows.append({"video": path, "split": s, "start": st, "end": en, "label": cls})
                secs[cls][s] += (D if en is None else en) - st
            print(f"  + {path}: {D/60:.1f} min -> cut by time into train/val/test  [{cls}]")
        else:
            total = sum(secs[cls].values())
            share = {s: (secs[cls][s] / total if total else 0.0) for s in SPLITS}
            s = max(SPLITS, key=lambda x: (TARGET[x] - share[x], -SPLITS.index(x)))
            new_rows.append({"video": path, "split": s, "start": 0.0, "end": None, "label": cls})
            secs[cls][s] += D
            print(f"  + {path}: {D:.0f}s -> {s}  [{cls}]")
        known.add(os.path.normcase(path))

if new_rows:
    append_rows(args.labels, new_rows)
    check_overlaps(read_rows(args.labels, CLASSES))
print(f"\n{len(new_rows)} row(s) added to {args.labels}")

print("\nseconds per class/split:")
print(f"{'':14}" + "".join(f"{s:>9}" for s in SPLITS))
for c in CLASSES:
    print(f"{c:14}" + "".join(f"{secs[c][s]:9.0f}" for s in SPLITS))
for c in CLASSES:
    missing = [s for s in ("val", "test") if secs[c][s] == 0]
    if secs[c]["train"] == 0:
        print(f"!! no training data for '{c}'")
    elif missing:
        print(f"!  '{c}' has nothing in {missing} -> can't be measured there until you add more videos")
