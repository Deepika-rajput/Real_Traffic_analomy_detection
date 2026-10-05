# Traffic Monitor: accident, sudden-stop and congestion detection

An end-to-end system that watches traffic video, classifies what it sees as **normal, accident, sudden stop or congestion**,
and lets a human operator review each alert (video clip, snapshot, map) before drafting emails to the nearest authorities.
Runs on a **CPU only** machine.

<img width="1892" height="880" alt="Screenshot 2026-10-05 234128" src="https://github.com/user-attachments/assets/d676cbf9-97a8-41d8-b62b-4ed2488aad2b" />


## What it does

- **Traffic classification:** Classifies traffic videos into 4 states — normal, accident, sudden stop, and congestion — using a CNN for spatial features, a Transformer for temporal patterns, and optical-flow motion features.
- **Web dashboard:** React-based interface with live camera tiles, an event review queue, evidence clips with the alert moment highlighted, and a map view.
- **Human-reviewed alerts:** Alerts are not sent automatically. An operator must confirm an event first. The system then identifies the nearest active police, hospital, or traffic-control contact, allows the message to be edited, and tracks acknowledgement with escalation to the next-nearest authority.
- **Feedback loop:** Confirmed events and dismissed false alarms can be exported as additional training data.
- **Dockerized deployment:** Docker Compose starts the FastAPI backend, model workers, and React frontend served through nginx.

## How the model works
```mermaid
flowchart LR
  V["Video or camera stream"] --> S["Sample ~5 frames per second"]
  S --> C["ResNet18, frozen<br/>appearance: 512 values"]
  S --> O["Optical flow on 96x96 gray<br/>motion: 15 values"]
  C --> W["Last 16 frames = 3.2 s"]
  O --> W
  W --> T["Small Transformer<br/>2 layers, CLS token"]
  T --> P["Probabilities:<br/>normal / accident / sudden stop / congestion"]
  P --> R["Per-class threshold<br/>+ k-of-N persistence"]
  R --> E["Alert event:<br/>clip + snapshot"]
```
- **Why a frozen CNN:** with ~12-15 videos per class, training a CNN from scratch overfits. The CNN runs once per sampled frame;
  features are cached, so training the Transformer takes minutes on CPU.
- **Why optical flow:** one frame cannot tell dense-and-flowing from dense-and-stopped traffic. Motion can.
- **Why persistence rules:** an alert needs several consistent predictions in a row (4 of the last 6), so a single noisy window
  never raises an alert.
- **Alert thresholds** are chosen per class from validation precision, not guessed.

## System design
```mermaid
flowchart LR
  subgraph Browser
    UI["React app<br/>live view, events, map"]
  end
  subgraph Docker
    NG["nginx"]
    API["FastAPI backend"]
    W["Camera workers<br/>model inference"]
    DB[("SQLite + clips")]
  end
  UI --> NG --> API
  API --> W
  W --> DB
  API --> DB
  API -.->|"after human confirms"| M["SMTP or outbox files"]
```

## Results 
| Test | Result |
|---|---|
| Holdout: 3 videos per class, never used in training, new sources | **11 / 12 videos correct** |

Reproduce with `python evaluate_folder.py --root holdout`.The holdout set contains 3 videos per class from sources not used during training.  
This is a small evaluation (12 videos), so the result should be treated as an
initial validation of the approach rather than a benchmark of real-world performance.

## Limitations

- **Limited data:** About 15 training videos per class. The accident class has fewer examples because suitable accident footage is harder to obtain.
- **Noisy whole-clip labels:** A video labeled as "sudden stop," for example, may contain several seconds of normal driving. Trimming clips to focus on the actual event improves label quality.
- **False alerts on long normal footage:** False-positive rates have not been measured rigorously. An early test on dense, flowing highway footage produced a few false alerts over approximately 7 minutes, before later improvements. The human-confirmation step is therefore important.
- **Camera dependence:** Training used a limited number of camera views. Performance may decrease on significantly different conditions such as night scenes, rain, or different camera angles.
- **Live-camera validation:** The system has only been tested on recorded clips and uploaded videos. RTSP and webcam streams are supported, but live-camera performance has not yet been validated.
- **Authority distance:** The "nearest authority" is selected using straight-line distance rather than actual driving time.
- **Contact information:** The project should use test email addresses during development. Real authority contacts require appropriate agreements and verification and are not provided by this project.

## Quick start (Docker)
Needs Docker Desktop. The trained model `temporal.pth` is included.
```
git clone <this repo>
cd <this repo>
copy .env.example .env           # Mac/Linux: cp .env.example .env
docker compose up --build
```
Open **http://localhost:8080** (API docs: http://localhost:8000/docs).

First tour:
1. **Authorities:** add test contacts (`@example.com` or your own address), or run
   `docker compose exec backend python backend/seed_demo.py --lat 28.6139 --lng 77.2090` (demo coordinates; use where your video was filmed).
2. **Cameras > Analyze an uploaded video:** pick a traffic video, click the map for its location, upload.
3. **Events:** open the new event, watch the clip, **Confirm**, edit the drafted emails, **Send**. Emails are dry-run by default
   (saved to the outbox, nothing leaves your machine).

Check which detector runs: http://localhost:8000/api/health shows `"mock_detector": false` for the real model.
`MOCK_DETECTOR=1` in `.env` gives scripted fake alerts for a UI-only demo.

## Run without Docker
```
pip install -r requirements.txt -r backend/requirements.txt
python -m uvicorn backend.app.main:app --port 8000
cd frontend && npm install && npm run dev        # http://localhost:5173
```

## Train on your own videos
Put videos in `videos/<class>/` (`normal`, `accident`, `sudden_stop`, `congestion`), then:
```
python make_labels.py          # adds new videos to labels.csv with an automatic train/val/test split
python extract_features.py     # one-time per video: CNN + motion features, cached; also makes augmented copies
python train.py                # trains, picks per-class thresholds, prints val/test results, saves temporal.pth
python evaluate_folder.py --root holdout     # honest test: videos in holdout/<class>/ never used in training
```
- **Trim clips to the event:** edit `labels.csv` rows (`video,split,start_s,end_s,label`). One video can have several rows
  (same split!), e.g. `sudden_stop` for 28-42 s and `normal` for the rest: free hard negatives from the same camera.
  `python peek_video.py <video> --every 5` helps find the timestamps.
- A video (or time range) belongs to **one split only**; the scripts refuse overlaps and duplicate files across class folders.
- Re-running only processes new or changed videos (cached by file and settings).
- Live sources (Cameras page): RTSP / HTTP stream URLs, or a webcam via `python tools/webcam_stream.py`.
  Inside Docker use `http://host.docker.internal:5001/video`.

## Configuration (`.env`)
| Variable | Meaning | Default |
|---|---|---|
| `MOCK_DETECTOR` | 1 = scripted fake alerts, 0 = real model | 0 |
| `SEND_MODE` | `dry_run` saves emails, `smtp` really sends | dry_run |
| `TEST_RECIPIENT` | if set, EVERY email goes to this one address | empty |
| `SMTP_HOST/PORT/USER/PASS`, `MAIL_FROM` | mail server for `smtp` mode | empty |
| `API_KEY` | require this key for the API (enter it in the app's settings) | empty (off) |
| `PUBLIC_BASE_URL` | address used for links inside emails | http://localhost:8080 |
| `MAX_RADIUS_KM`, `ACK_TIMEOUT_MIN`, `COOLDOWN_S` | authority search radius, escalation wait, duplicate-alert window | 50, 10, 90 |

Never commit `.env` (it is in `.gitignore`).

## Project structure
```
src/                 model, detector, motion features, augmentation, label helpers
make_labels.py  extract_features.py  train.py  evaluate_folder.py  detect.py  peek_video.py
labels.csv           which video/time range has which label
temporal.pth         trained Transformer weights (small)
backend/app/         FastAPI app: cameras, events, clips, alerts, authorities, training export
backend/tests/       backend smoke test (works without a trained model)
frontend/            React app (Vite) + nginx config
tools/               webcam_stream.py: publish a webcam as a stream for Docker
Dockerfile  docker-compose.yml  .env.example
videos/  holdout/    your data (not committed)
```

## Tech stack
PyTorch (CPU), torchvision ResNet18, OpenCV (optical flow, video I/O), FastAPI, SQLite, ffmpeg (browser-playable clips),
React + Vite, Leaflet + OpenStreetMap, Docker Compose, nginx.

## Roadmap
More accident data and cross-validation for steadier numbers; false-alert-per-hour measurement on long footage; webcam capture
straight from the browser; a normal-only anomaly score to catch unseen event types; hard-negative mining from operator dismissals.

## Data and licensing
Training videos are not included (size, and the sources have their own licenses). Check each source's license before
redistributing footage.
