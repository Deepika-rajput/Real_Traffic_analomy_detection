"""Run the trained model on ANY video, folder of videos, or webcam. Folders are not tied to classes.

    python detect.py --source D:\\any\\path\\video.mp4
    python detect.py --source D:\\any\\folder              (all videos inside, recursive)
    python detect.py --source 0                           (webcam)
    python detect.py --source D:\\any\\folder --no-show --save    (no window, write annotated copies to runs/)
"""
import argparse
import os
import time
from collections import Counter

import cv2

from src.detector import StreamDetector

VID_EXT = (".mp4", ".avi", ".mov", ".mkv", ".m4v", ".webm")
COLORS = {
    "LOADING": (255, 255, 0),
    "NORMAL": (0, 255, 0),
    "WARNING": (0, 165, 255),
    "ACCIDENT": (0, 0, 255),
    "SUDDEN_STOP": (0, 0, 255),
    "CONGESTION": (0, 100, 255),
}

ap = argparse.ArgumentParser()
ap.add_argument("--source", required=True, help="video file, folder, or webcam index")
ap.add_argument("--weights", default="temporal.pth")
ap.add_argument("--no-show", action="store_true", help="don't open a window")
ap.add_argument("--save", action="store_true", help="write annotated video(s) to runs/")
args = ap.parse_args()


def list_sources(src):
    if src.isdigit():
        return [int(src)]
    if os.path.isdir(src):
        found = []
        for root, _, files in os.walk(src):
            found += [os.path.join(root, f) for f in files if f.lower().endswith(VID_EXT)]
        return sorted(found)
    return [src]


def run(det, source):
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"  ! cannot open {source}")
        return
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0          # webcams may report 0 -> assume 25
    det.set_fps(fps)
    writer = None
    if args.save:
        os.makedirs("runs", exist_ok=True)
        name = "webcam" if isinstance(source, int) else os.path.splitext(os.path.basename(source))[0]
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        writer = cv2.VideoWriter(os.path.join("runs", name + "_out.mp4"),
                                 cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))

    n, t0, states, events = 0, time.time(), Counter(), []
    while cap.isOpened():
        ok, frame = cap.read()
        if not ok:
            break
        res = det.process(frame)
        n += 1
        states[res["state"]] += 1
        if res["event"]:
            e = res["event"]
            events.append((n / fps, e["type"], e["label"], e["prob"]))
            print(f"  [{n / fps:7.1f}s] {e['type'].upper()} {e['label']} (p={e['prob']:.2f})")

        if writer or not args.no_show:
            color = COLORS[res["state"]]
            title = res["state"] + (f" ({res['label']})" if res["state"] == "WARNING" else "")
            # OpenCV can't draw emojis, so plain text only.
            cv2.putText(frame, title, (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 3)
            for k, (cname, p) in enumerate(res["probs"].items()):
                cv2.putText(frame, f"{cname}: {p:.2f}", (30, 90 + 28 * k),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            if writer:
                writer.write(frame)
            if not args.no_show:
                cv2.imshow("Traffic anomaly detection", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    cap.release()
                    raise KeyboardInterrupt

    cap.release()
    if writer:
        writer.release()
    total = max(1, sum(states.values()))
    summary = ", ".join(f"{s} {100 * c / total:.0f}%" for s, c in states.most_common())
    starts = [e for e in events if e[1] == "start"]
    print(f"  done: {n} frames in {time.time() - t0:.0f}s ({n / max(1e-6, time.time() - t0):.1f} fps) | "
          f"{len(starts)} alert(s) | {summary}")


det = StreamDetector(args.weights)
sources = list_sources(args.source)
if not sources:
    raise SystemExit(f"no videos found in {args.source}")
try:
    for s in sources:
        print(f"\n{s}")
        run(det, s)
except KeyboardInterrupt:
    pass
cv2.destroyAllWindows()
