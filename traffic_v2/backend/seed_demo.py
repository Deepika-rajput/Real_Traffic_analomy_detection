"""Add DEMO authorities (and optionally cameras) through the running API.

    # 1) start the server, 2) in another terminal, from the project root:
    python backend/seed_demo.py --lat 28.6139 --lng 77.2090
    python backend/seed_demo.py --lat 28.6139 --lng 77.2090 --video videos/accident/acc1.mp4

If you set API_KEY for the server, pass it:  --key your-key
Authorities are FAKE and use @example.com (a reserved domain that can never receive mail),
placed a few km around the camera. Coordinates are demo values: pass the real camera's.
Replace with real authority contacts only when you are ready (and keep TEST_RECIPIENT set).
"""
import argparse
from pathlib import Path

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://127.0.0.1:8000")
ap.add_argument("--key", default="")
ap.add_argument("--lat", type=float, default=28.6139)
ap.add_argument("--lng", type=float, default=77.2090)
ap.add_argument("--video", action="append", default=[], help="add a demo camera for this video (repeatable)")
args = ap.parse_args()

root = Path(__file__).resolve().parents[1]
http = httpx.Client(base_url=args.base, headers={"X-API-Key": args.key} if args.key else {}, timeout=30)

demo = [
    ("Demo Police Station A", "police", 0.020, 0.010),
    ("Demo Police Station B", "police", -0.060, 0.050),
    ("Demo Trauma Hospital", "hospital", 0.030, -0.020),
    ("Demo City Hospital", "hospital", 0.150, 0.120),
    ("Demo Highway Traffic Control", "traffic_control", -0.010, 0.030),
]
have = {a["name"] for a in http.get("/api/authorities").raise_for_status().json()}
for name, typ, dlat, dlng in demo:
    if name in have:
        continue
    r = http.post("/api/authorities", json={
        "name": name, "type": typ, "lat": round(args.lat + dlat, 5), "lng": round(args.lng + dlng, 5),
        "email": f"{typ}.{name.split()[-1].lower()}@example.com"})
    print("authority:", name, "->", r.status_code)

for v in args.video:
    p = Path(v) if Path(v).is_absolute() else root / v
    if not p.exists():
        print("! video not found:", v)
        continue
    r = http.post("/api/cameras", json={"name": f"Demo camera: {p.stem}", "source": str(p.resolve()),
                                         "lat": args.lat, "lng": args.lng, "loop": True, "realtime": True})
    print("camera:", p.name, "->", r.status_code, r.json().get("id"))
print("done. Open", args.base + "/docs")
