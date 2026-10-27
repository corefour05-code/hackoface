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
DETECTION_SIZE = (480, 480)            # 480x480 for fast ~10ms SCRFD detector inference on CPU

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
COSINE_MATCH_THRESHOLD = 0.48          # fast, immediate first-frame match (cross-person avg is ~0.09)
MATCH_MARGIN = 0.04                    # margin against runner-up identities to prevent false accepts
MIN_FACE_SIZE_PX = 50                  # reject tiny/far-away detections

# --- Analytics ---
LAB_CLASS_MIN_STUDENTS = 35
ANALYTICS_SESSION_GAP_MINUTES = 15

# --- Enrollment ---
ENROLLMENT_SHOTS_PER_STUDENT = 5
ENROLLMENT_ANGLE_LABELS = ["center", "left", "right", "up", "down"]
BLUR_LAPLACIAN_VAR_THRESHOLD = 80.0    # below this variance, image is considered too blurry

# --- Attendance Rules & Timing ---
# Exactly 30 seconds required between transitions:
# 1. After checking IN: must stay in room at least 30 seconds before checking OUT.
# 2. After checking OUT: must wait at least 30 seconds before checking back IN.
MIN_ROOM_STAY_SECONDS = 30
REENTRY_LOCK_SECONDS = 30
DEDUP_WINDOW_SECONDS = 30
DEDUP_WINDOW_MINUTES = 0.5

# --- Web app auth ---
ATTENDANCE_PASSCODE = "attendance123"  # gate before the scanner login (Page 5)
DEFAULT_CLEAR_LAB_PASSWORD = "clear123"
EDIT_RECAPTURE_SHOTS = 2               # photos required when re-capturing faces on Edit pages

# --- Seed (db/seed.py) ---
SEED_MAIN_LAB_NAME = "Main Lab"
SEED_ADMIN_USERNAME = "admin"
SEED_ADMIN_PASSWORD = "admin123"       # change via Manage Users after first login
