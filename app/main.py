"""FastAPI app: session auth + Jinja2 admin UI for the multi-lab attendance platform."""

import asyncio
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
from app.routers import batch as batch_router
from app.routers import capture as capture_router
from app.routers import faculty as faculty_router
from app.routers import labs as labs_router
from app.routers import periods as periods_router
from app.routers import register as register_router
from app.routers import report as report_router
from app.routers import scanner as scanner_router
from app.routers import shutdown as shutdown_router
from app.routers import students as students_router
from app.routers import users as users_router

STATIC_DIR = Path(__file__).resolve().parent / "static"
SHUTDOWN_CHECK_INTERVAL_SECONDS = 20

app = FastAPI(title="PSNA Lab Attendance System")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)


@app.on_event("startup")
def startup() -> None:
    from db.init_db import init_db

    init_db()
    recognizer = state.init_recognizer()
    print(f"Loaded {len(recognizer.identities)} embeddings "
          f"across {len(set(recognizer.identities))} identities.")


@app.on_event("startup")
async def start_shutdown_time_scheduler() -> None:
    async def _loop():
        while True:
            try:
                shutdown_router.run_due_shutdowns()
            except Exception as e:
                print(f"[shutdown-time] scheduler error: {e}")
            await asyncio.sleep(SHUTDOWN_CHECK_INTERVAL_SECONDS)

    # asyncio only holds a weak reference to a bare create_task() result — with
    # nothing else referencing it, the task can be garbage-collected before it
    # ever runs. Stashing it on app.state keeps a strong reference alive for
    # the process lifetime.
    app.state.shutdown_scheduler_task = asyncio.create_task(_loop())


app.include_router(analytics_router.router)
app.include_router(auth_router.router)
app.include_router(batch_router.router)
app.include_router(capture_router.router)
app.include_router(students_router.router)
app.include_router(faculty_router.router)
app.include_router(labs_router.router)
app.include_router(periods_router.router)
app.include_router(shutdown_router.router)
app.include_router(users_router.router)
app.include_router(scanner_router.router)
app.include_router(report_router.router)
app.include_router(register_router.router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
