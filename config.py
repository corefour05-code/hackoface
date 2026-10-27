"""Central configuration for the attendance system. Tune these without touching logic."""

import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "attendance.db"
ENROLLMENT_PHOTOS_DIR = DATA_DIR / "enrollment_photos"


def _load_or_create_secret_key() -> str:
    key_path = DATA_DIR / ".secret_key"
    if key_path.exists():
        return key_path.read_text().strip()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    key_path.write_text(key)
    return key


SECRET_KEY = _load_or_create_secret_key()

# --- Model ---
INSIGHTFACE_MODEL_NAME = "buffalo_s"   # SCRFD-500MF detector + lightweight recognition model
INSIGHTFACE_CTX_ID = -1                # -1 = CPU
DETECTION_SIZE = (640, 640)            # insightface det_size, input to SCRFD

# --- Camera / frame pipeline ---
CAMERA_SOURCE = "webcam"               # Client-side native WebRTC laptop camera
CAMERA_INDEX = 0
STREAM_FPS = 30
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
DETECT_EVERY_N_FRAMES = 3              # run detection every Nth frame; reuse last result otherwise
MOTION_TRIGGER_ENABLED = True
MOTION_DIFF_THRESHOLD = 25             # per-pixel intensity diff threshold for motion trigger
MOTION_MIN_CHANGED_PIXELS_RATIO = 0.02 # fraction of pixels that must change to count as motion

# --- Matching ---
COSINE_MATCH_THRESHOLD = 0.55          # configurable per requirement 5 (~0.5-0.6)
MATCH_MARGIN = 0.05                    # best match must beat the best *other* identity by
                                        # at least this much, else treated as unknown — guards
                                        # against false accepts as the enrolled pool grows
MIN_FACE_SIZE_PX = 60                  # reject tiny/far-away detections

# --- Analytics ---
# Minimum distinct students from the same (year, section) checked into the
# same period+lab to count that group as a scheduled lab class rather than
# individual/project attendance. Overridable per-request on the Analytics page.
LAB_CLASS_MIN_STUDENTS = 35

# A student's same-day, same-lab attendance rows are merged into one session
# when the gap between an OUT and the next IN is within this many minutes —
# treated as a short break (stepping out and back in), not a separate visit.
# A longer gap (e.g. class ended, then a lone comeback periods later) starts
# a new, independently-classified session instead.
ANALYTICS_SESSION_GAP_MINUTES = 15

# --- Enrollment ---
ENROLLMENT_SHOTS_PER_STUDENT = 5
ENROLLMENT_ANGLE_LABELS = ["center", "left", "right", "up", "down"]
BLUR_LAPLACIAN_VAR_THRESHOLD = 80.0    # below this variance, image is considered too blurry

# --- Attendance dedup ---
# Rapid re-scan toggle window (in seconds). A scan within this threshold re-confirms current status
# without rapid double-flipping; a scan after 5 seconds toggles IN <-> OUT smoothly.
# Every scan is also recorded into scan_logs for duplicate & full audit data.
DEDUP_WINDOW_SECONDS = 5
DEDUP_WINDOW_MINUTES = 0.1

# --- Web app auth ---
ATTENDANCE_PASSCODE = "attendance123"  # gate before the scanner login (Page 5)
DEFAULT_CLEAR_LAB_PASSWORD = "clear123"
EDIT_RECAPTURE_SHOTS = 2               # photos required when re-capturing faces on Edit pages

# --- Seed (db/seed.py) ---
SEED_MAIN_LAB_NAME = "Main Lab"
SEED_ADMIN_USERNAME = "admin"
SEED_ADMIN_PASSWORD = "admin123"       # change via Manage Users after first login
