# PyInstaller spec for the standalone desktop build.
#
# Bundles the app code, templates/static assets, the DB schema, and a local
# copy of the InsightFace buffalo_s weights (staged by stage_models.py) so
# the packaged app runs fully offline on a client machine with no Python
# install and no internet access needed for the model.
#
# Build with: pyinstaller software/build.spec (see build.bat)

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve().parent
STAGED_MODELS = PROJECT_ROOT / "software" / "_build" / "insightface_home"

if not STAGED_MODELS.exists():
    raise SystemExit(
        "Staged InsightFace models not found — run "
        "`python software/stage_models.py` before building."
    )

datas = [
    (str(PROJECT_ROOT / "app" / "templates"), "app/templates"),
    (str(PROJECT_ROOT / "app" / "static"), "app/static"),
    (str(PROJECT_ROOT / "db" / "schema.sql"), "db"),
    (str(STAGED_MODELS), "insightface_home"),
]

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "onnxruntime",
    "insightface",
]

a = Analysis(
    [str(PROJECT_ROOT / "software" / "launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AttendanceApp",
    console=True,  # keep visible for now so a client can see startup errors
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="AttendanceApp",
)
