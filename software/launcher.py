"""Entry point for the packaged desktop build (PyInstaller).

Not imported by the main app — this only exists to wire up things that are
only true when frozen: pointing InsightFace at the bundled model weights
(instead of downloading them), locating the project root inside the bundle,
and starting the server + opening a browser like a desktop app instead of
requiring `uvicorn app.main:app` on a command line.

InsightFace resolves its default model root as `~/.insightface`, expanded
via `os.path.expanduser`. On Windows that reads the `USERPROFILE` env var.
Setting it here (before `core.face_engine` ever runs) redirects that lookup
to a folder we bundled ourselves, so a client machine never needs internet
access or the real user's `.insightface` cache. Nothing in the main app
(core/face_engine.py) needs to change for this to work.
"""

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

PORT = 8001


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # PyInstaller's extraction/onedir root
    return Path(__file__).resolve().parent


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return _bundle_root()
    return Path(__file__).resolve().parent.parent


def _use_bundled_insightface_models() -> None:
    bundled_home = _bundle_root() / "insightface_home"
    if bundled_home.exists():
        os.environ["USERPROFILE"] = str(bundled_home)
        os.environ["HOME"] = str(bundled_home)


def _open_browser_soon() -> None:
    time.sleep(1.5)
    webbrowser.open(f"http://127.0.0.1:{PORT}")


def main() -> None:
    _use_bundled_insightface_models()

    project_root = _project_root()
    sys.path.insert(0, str(project_root))

    from db.seed import seed

    # seed() calls init_db() itself, then creates the Main Lab + default
    # admin user if they don't exist yet — a fresh install otherwise has
    # tables but no account to log into.
    seed()

    import uvicorn

    from app.main import app

    threading.Thread(target=_open_browser_soon, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT)


def _exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        crash_log = _exe_dir() / "crash_log.txt"
        crash_log.write_text(traceback.format_exc())
        print("\n\n=== AttendanceApp failed to start ===")
        print(traceback.format_exc())
        print(f"(also written to {crash_log})")
        input("\nPress Enter to close this window...")
