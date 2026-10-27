"""FastAPI application for PSNA IT Department 24-Hour Hackathon Face Recognition Attendance Platform."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from config import SECRET_KEY
from app import state
from app.routers import analytics as analytics_router
from app.routers import auth as auth_router
from app.routers import capture as capture_router
from app.routers import labs as labs_router
from app.routers import register as register_router
from app.routers import report as report_router
from app.routers import scanner as scanner_router
from app.routers import students as students_router
from app.routers import users as users_router

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="PSNA 24-Hour Hackathon Face Recognition Platform")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)


@app.on_event("startup")
def startup() -> None:
    from db.init_db import init_db

    init_db()
    recognizer = state.init_recognizer()
    print(f"Loaded {len(recognizer.identities)} embeddings across {len(set(recognizer.identities))} identities.")


@app.on_event("shutdown")
def shutdown_event() -> None:
    from core.rtsp_stream import get_stream_manager
    get_stream_manager().stop()


app.include_router(analytics_router.router)
app.include_router(auth_router.router)
app.include_router(capture_router.router)
app.include_router(students_router.router)
app.include_router(labs_router.router)
app.include_router(users_router.router)
app.include_router(scanner_router.router)
app.include_router(report_router.router)
app.include_router(register_router.router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
