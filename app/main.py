import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.routers import sessions, users, workout
from app.services.workout_manager import workout_manager
from app.version import VERSION

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="WaterRower Dashboard", version=VERSION)
app.include_router(users.router)
app.include_router(sessions.router)
app.include_router(workout.router)


@app.get("/api/version")
def get_version() -> dict[str, str]:
    return {"version": VERSION}


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    logger.info("WaterRower Dashboard v%s", VERSION)
    print(f"WaterRower Dashboard v{VERSION}", flush=True)
    logger.info("Database ready")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await workout_manager.register_ws(ws)
    try:
        while True:
            # Keepalive / ignore client pings
            await ws.receive_text()
    except WebSocketDisconnect:
        workout_manager.unregister_ws(ws)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
