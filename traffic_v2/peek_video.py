"""Contact sheets with timestamps so you can find segments to label.

    python peek_video.py video\traffic1.mp4 --every 30

Writes peek_<name>_<k>.jpg (24 thumbnails each). Open them, note start/end seconds of
congestion / sudden stop / accident, and put them in labels.csv.
"""
import argparse
import os

import cv2

ap = argparse.ArgumentParser()
ap.add_argument("video")
ap.add_argument("--every", type=float, default=30, help="seconds between thumbnails")
ap.add_argument("--out", default=".")
args = ap.parse_args()

cap = cv2.VideoCapture(args.video)
fps = cap.get(cv2.CAP_PROP_FPS) or 25
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
dur = n / fps
name = os.path.splitext(os.path.basename(args.video))[0]
print(f"{name}: {dur:.1f}s @ {fps:.1f}fps")

tiles, sheet, t = [], 0, 0.0
def flush():
    global tiles, sheet
    if not tiles:
        return
    while len(tiles) % 6:
        tiles.append(tiles[-1] * 0)
    rows = [cv2.hconcat(tiles[i:i + 6]) for i in range(0, len(tiles), 6)]
    path = os.path.join(args.out, f"peek_{name}_{sheet}.jpg")
    cv2.imwrite(path, cv2.vconcat(rows))
    print("wrote", path)
    tiles, sheet = [], sheet + 1

while t < dur:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
    ok, f = cap.read()
    if ok:
        f = cv2.resize(f, (320, 180))
        cv2.putText(f, f"{int(t)}s", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        tiles.append(f)
    if len(tiles) == 24:
        flush()
    t += args.every
flush()
