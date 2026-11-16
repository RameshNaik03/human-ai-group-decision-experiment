import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from . import db
from .config import load_config
from .session import SessionManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

cfg = load_config()
manager = SessionManager(cfg)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.getLogger("main").info("Condition '%s': %s", cfg.condition, cfg.participant_types)
    await db.init()
    yield


app = FastAPI(title="CHM Group Decision Experiment", lifespan=lifespan)


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/settings")
async def settings():
    return cfg.public()   # deliberately excludes participant types


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session, label = await manager.join(ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                await session.handle(label, data)
    except (WebSocketDisconnect, RuntimeError):
        pass    # RuntimeError: receive after the server closed the socket (waiting-room timeout)
    finally:
        await manager.leave(session, label, ws)
