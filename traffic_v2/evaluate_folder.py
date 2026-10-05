"""Honest evaluation on videos the model has NEVER seen (not in labels.csv, not in videos/).

    holdout/normal/*.mp4   holdout/accident/*.mp4   holdout/sudden_stop/*.mp4   holdout/congestion/*.mp4

    python evaluate_folder.py --root holdout

Each video is run through the real detector. Its predicted class = the anomaly with the most
alert time (or 'normal' if it never alerted). Prints per-video results and a confusion table.
Use videos from DIFFERENT cameras/sources than your training set, that is the real test.
"""
import argparse
import os
from collections import Counter

import cv2

from src.config import ANOMALIES, CLASSES

VID_EXT = (".mp4", ".avi", ".mov", ".mkv", ".m4v", ".webm")


def classify_video(det, path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    det.set_fps(fps)
    alert_frames, n, first = Counter(), 0, None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        n += 1
        res = det.process(frame)
        if res["label"] and res["state"] != "WARNING":
            alert_frames[res["label"]] += 1
            if first is None:
                first = n / fps
    cap.release()
    pred = alert_frames.most_common(1)[0][0] if alert_frames else "normal"
    return {"pred": pred, "first": first, "secs": {c: alert_frames[c] / fps for c in ANOMALIES},
            "dur": n / fps}


def print_report(results):
    """results: list of (true_class, video_path, result_dict)"""
    print("\nper video:")
    for true, path, r in results:
        flag = "ok " if r["pred"] == true else "XX "
        extra = "" if r["first"] is None else f", first alert at {r['first']:.1f}s"
        alerts = ", ".join(f"{c} {s:.0f}s" for c, s in r["secs"].items() if s > 0) or "no alerts"
        print(f"  {flag}{true:12} -> {r['pred']:12} {os.path.basename(path)[:40]:40} ({alerts}{extra})")

    print("\nconfusion (rows = true, cols = predicted):")
    print(f"{'':14}" + "".join(f"{c[:11]:>12}" for c in CLASSES))
    for t in CLASSES:
        row = [sum(1 for tt, _, r in results if tt == t and r["pred"] == p) for p in CLASSES]
        if sum(row):
            print(f"{t:14}" + "".join(f"{v:12d}" for v in row) + f"   recall {row[CLASSES.index(t)]}/{sum(row)}")
    normal = [r for t, _, r in results if t == "normal"]
    if normal:
        fa = sum(1 for r in normal if r["pred"] != "normal")
        print(f"\nnormal videos that raised a false alert: {fa}/{len(normal)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="holdout")
    ap.add_argument("--weights", default="temporal.pth")
    args = ap.parse_args()

    from src.detector import StreamDetector          # imported here so the report code is torch-free
    det = StreamDetector(args.weights)
    results = []
    for cls in CLASSES:
        folder = os.path.join(args.root, cls)
        if not os.path.isdir(folder):
            continue
        for f in sorted(os.listdir(folder)):
            if f.lower().endswith(VID_EXT):
                path = os.path.join(folder, f)
                print(f"running {path} ...", flush=True)
                r = classify_video(det, path)
                if r:
                    results.append((cls, path, r))
    if not results:
        raise SystemExit(f"no videos found under {args.root}/<class>/")
    print_report(results)