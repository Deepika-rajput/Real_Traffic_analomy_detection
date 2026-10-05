# Traffic Anomaly API (FastAPI)

Runs your trained detector on cameras/uploads, records the video around every alert, and gives
an operator a review queue. Emails to authorities only go out after a human confirms.

```
camera / uploaded video -> worker thread -> StreamDetector (your model)
        -> event + snapshot + H.264 clip (8 s before, until end, 6 s after)
        -> SQLite  -> REST API + WebSocket + MJPEG  -> frontend (next step)
        -> operator Confirm -> nearest authority drafts -> Send -> Ack / escalate
```

## Run (from the project root, next to detect.py)
```
pip install -r backend/requirements.txt

# no trained model yet / UI work:  fake detector that raises scripted alerts
$env:MOCK_DETECTOR="1"          # PowerShell.   (cmd: set MOCK_DETECTOR=1)
python -m uvicorn backend.app.main:app --port 8000

# real model (needs temporal.pth from train.py): just don't set MOCK_DETECTOR
python -m uvicorn backend.app.main:app --port 8000
```
Open http://localhost:8000/docs for the interactive API. Data lives in `backend_data/`
(database, clips, snapshots, uploads, outbox). `python backend/tests/smoke_test.py` runs the
whole flow with the mock detector (no model needed).

## Try it in 2 minutes
1. `python backend/seed_demo.py` (adds DEMO authorities and a camera, edit the values first).
2. Upload any video: `POST /api/uploads` (in /docs) with optional lat/lng.
3. Poll `GET /api/cameras/{id}/status` until `finished`, then `GET /api/events?camera_id={id}`.
4. `GET /api/events/{id}/clip` plays in a browser. `POST /api/events/{id}/confirm` drafts the emails.
5. `POST /api/events/{id}/alerts/send-all`. In the default dry-run mode the emails land as `.eml`
   files in `backend_data/outbox/`. Nothing is sent.

## How false reports are kept out
1. Detector: per-class threshold + k-of-N persistence (already in `src/detector.py`).
2. Flapping alerts within the clip's post-roll merge into one event; repeats within 90 s are flagged
   `duplicate_of` and hidden from the default queue.
3. Severity tiers (low / medium / high from peak probability) to sort the queue.
4. **Nothing is drafted or sent until an operator confirms** (enforced in `alerts.py`, not only in the routes).
5. `SEND_MODE=dry_run` by default; `TEST_RECIPIENT` redirects every email to one inbox while you develop.
6. Recipients: nearest active authority of each needed type within `MAX_RADIUS_KM` (accident = police +
   hospital, sudden stop / congestion = traffic control). No camera coordinates or no authority in range =
   a clear message, never a guess. Unacknowledged alerts escalate to the next-nearest authority.
7. Every Dismiss(false_alarm) becomes a hard negative via `POST /api/training/export`.

## Endpoints
| | |
|---|---|
| `GET/POST/PATCH/DELETE /api/cameras`, `POST .../start`, `.../stop`, `GET .../status`, `GET .../stream` (MJPEG live preview) | cameras |
| `POST /api/uploads` | analyse any video through the same detector |
| `GET /api/events` (filters: camera_id, label, status, severity, include_duplicates) , `GET /api/events/{id}`, `.../clip` (Range), `.../snapshot` | events |
| `POST /api/events/{id}/confirm`, `.../dismiss` | operator review |
| `POST /api/events/{id}/alerts/draft`, `.../alerts/send-all`, `PATCH/POST/DELETE /api/alerts/{id}[/send]` | alerts |
| `GET/POST/PATCH/DELETE /api/authorities` | who gets emailed |
| `GET /api/stats` | counts, operator-measured precision |
| `POST /api/training/export`, `POST /api/training/upload` | feed reviewed clips / new videos back into `videos/<class>/` |
| `WS /ws/events` | live push: `{"type":"event","action":"created"|"updated","event":{...}}` |
| `GET /public/events/{id}/clip?t=...`, `/public/ack/{token}` | signed links used inside emails |

Set `API_KEY` to require `X-API-Key` (or `?key=` for `<img>`/`<video>` tags). Pass `X-Operator: name`
so reviews record who confirmed. See `.env.example` for every setting.

## CPU notes
Each running camera is one detector (ResNet18 at 5 fps + a tiny transformer). On a laptop CPU run
1-2 live cameras; uploads are processed as fast as the CPU allows. Clips are stored at <= 854 px wide.

## Known limits
* Camera/upload workers restart with the server only for `kind=stream` cameras with `enabled=1`.
* SQLite is fine for a project/demo; move to Postgres for real deployments.
* The model + detector were tested on your videos; the backend was tested end to end with the mock
  detector (this sandbox has no torch). First real run: watch the terminal for the detector's errors.
