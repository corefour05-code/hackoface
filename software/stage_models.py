"""Copy the locally-cached InsightFace buffalo_s model weights into a
build-local staging folder so build.spec can bundle them into the package.
Keeps the ~150MB of .onnx weights out of git and out of the build script
itself — run this once before packaging (build.bat does it automatically).
"""

import shutil
from pathlib import Path

SOURCE = Path.home() / ".insightface" / "models" / "buffalo_s"
# launcher.py points USERPROFILE/HOME at insightface_home/ so InsightFace's
# own `expanduser('~/.insightface')` lookup lands here — note the extra
# ".insightface" segment, it's not redundant.
DEST = (
    Path(__file__).resolve().parent
    / "_build" / "insightface_home" / ".insightface" / "models" / "buffalo_s"
)


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(
            f"Model cache not found at {SOURCE}.\n"
            "Run the app locally at least once first so InsightFace downloads "
            "buffalo_s, then re-run this script."
        )

    DEST.mkdir(parents=True, exist_ok=True)
    copied = 0
    for f in SOURCE.glob("*.onnx"):
        shutil.copy2(f, DEST / f.name)
        copied += 1

    if copied == 0:
        raise SystemExit(f"No .onnx files found in {SOURCE} — nothing staged.")

    print(f"Staged {copied} model file(s) into {DEST}")


if __name__ == "__main__":
    main()
