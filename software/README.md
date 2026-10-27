# Packaged desktop build

Turns the web app into a standalone Windows `.exe` a client can double-click
and run — no Python install, no internet access needed, and no access to
the source code. This folder is self-contained; nothing in the main project
(`app/`, `core/`, `db/`, `config.py`, etc.) was changed to make this work.

## How it works

- **`launcher.py`** is the actual entry point (not `app/main.py` directly).
  It starts `uvicorn` in-process, serving the same FastAPI app, and opens
  the client's default browser to `http://127.0.0.1:8001` automatically —
  so it feels like a desktop app, not something they have to know is a web
  server.
- Before starting, it points InsightFace at a **bundled copy** of the
  `buffalo_s` model weights instead of letting it download from the
  internet on first run. It does this by overriding the `USERPROFILE`/`HOME`
  environment variables for the process only, since InsightFace resolves its
  model folder as `~/.insightface` — no code in `core/face_engine.py` had to
  change for this.
- `db/init_db.py` still runs on every launch (same as always — safe/idempotent),
  so a fresh install creates its own empty `attendance.db` automatically.

## Building it

```
software\build.bat
```

This will (in order):
1. Install PyInstaller into the project's `.venv` if not already present.
2. Run `stage_models.py`, which copies your locally-cached InsightFace
   model weights (from `%USERPROFILE%\.insightface\models\buffalo_s`) into
   `software/_build/insightface_home/` so they can be bundled. **You must
   have run the app locally at least once already** so those weights exist
   on your machine — the packaged build only ever bundles what's already
   cached, it never re-downloads.
2. Run PyInstaller against `build.spec` (onedir mode — a folder, not a
   single-file exe, so the DB and cache persist properly between runs).

Output: `software/dist/AttendanceApp/AttendanceApp.exe` (plus a required
`_internal/` folder next to it — the whole `AttendanceApp` folder is what
you hand to a client, not just the .exe alone).

## Known limitations (first version — fine for now, worth revisiting later)

- **Where the DB lives**: `config.py` computes `data/attendance.db` relative
  to its own file location, which we didn't touch — so in the packaged
  build, the database ends up inside `AttendanceApp/_internal/data/`. It's
  real and persists between runs (this is a proper on-disk folder, not a
  temp extraction — that's specifically why we build in `--onedir` mode,
  not `--onefile`), but it means **don't delete or reinstall over the
  `AttendanceApp` folder** without backing up `_internal/data/` first. A
  cleaner v2 would move the DB to `%APPDATA%` — that does require a small
  `config.py` change (a `sys.frozen` check), left out for now since the
  request was explicitly not to touch the main app.
- **Console window stays visible** (`console=True` in `build.spec`) so
  startup errors are visible while we're still validating this on real
  client machines. Flip to `console=False` once you're confident it's solid,
  for a cleaner look.
- **Camera access needs `localhost`**: since this runs entirely on
  `127.0.0.1` on the client's own machine, browser webcam permissions work
  fine out of the box — this limitation only applies if you ever expose it
  over a network instead (see the earlier discussion on hosting a shared
  instance, which is a different deployment model from this one).
- No installer/uninstaller yet (e.g. Inno Setup) — right now it's "copy the
  folder, run the exe." Fine for a pilot handoff; worth wrapping in a proper
  installer before wider distribution.

## Distributing to a client

Zip the whole `software/dist/AttendanceApp/` folder and send it to them
(USB/drive link — don't commit it to git, it's gitignored and ~1GB+ with
all the bundled ML libraries). They unzip anywhere and run
`AttendanceApp.exe`. First launch takes a few seconds longer while the
detection/recognition models initialize.
