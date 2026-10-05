"""Traffic anomaly API.   Run from the project root:

    uvicorn backend.app.main:app --reload --port 8000
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .alerts import escalate_overdue
from .api import public, router
from .config import settings
from .db import DB
from .state import state
from .worker import Manager


async def escalation_loop():
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(30)
        try:
            await loop.run_in_executor(None, escalate_overdue, state.db)
        except Exception as e:                       # noqa: BLE001
            print("escalation error:", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    state.db = DB(settings.db_path)
    state.manager = Manager(state.db)
    state.manager.loop = asyncio.get_running_loop()
    if not settings.api_key:
        print("WARNING: API_KEY is not set, the API is open. Fine for local dev, not for deployment.")
    if settings.send_mode == "smtp" and not settings.test_recipient:
        print("WARNING: SEND_MODE=smtp without TEST_RECIPIENT: emails will go to the REAL authority addresses.")
    for cam in state.db.all("SELECT * FROM cameras WHERE enabled=1 AND kind='stream'"):
        try:
            state.manager.start_camera(cam["id"])
        except Exception as e:                       # noqa: BLE001
            print(f"could not start camera {cam['id']}: {e}")
    task = asyncio.create_task(escalation_loop())
    yield
    task.cancel()
    state.manager.stop_all()
    state.db.close()


app = FastAPI(title="Traffic Anomaly Detection API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                   allow_headers=["*"], allow_credentials=False)
app.include_router(public)
app.include_router(router)


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    """Live push of event created/updated messages: {"type":"event","action":"created","event":{...}}"""
    if settings.api_key and ws.query_params.get("key") != settings.api_key:
        await ws.close(code=4401)
        return
    await ws.accept()
    state.manager.clients.add(ws)
    try:
        await ws.send_json({"type": "hello"})
        while True:
            await ws.receive_text()                  # keep-alive; clients may send pings
    except WebSocketDisconnect:
        pass
    finally:
        state.manager.clients.discard(ws)
