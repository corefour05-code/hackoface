"""Enroll a student: capture several angles via webcam, validate each capture,
generate embeddings, and store them in the DB.

Usage:
    python enrollment/enroll.py --roll_no 23it112 --name "Jane Doe" --year 2 --department IT

Controls during capture:
    SPACE - attempt a capture for the current angle
    ESC   - cancel enrollment (nothing is written to the DB)
"""

import argparse
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    CAMERA_INDEX,
    ENROLLMENT_ANGLE_LABELS,
    ENROLLMENT_PHOTOS_DIR,
    FRAME_HEIGHT,
    FRAME_WIDTH,
)
from core.face_engine import get_face_app
from db.connection import get_connection
from enrollment.validation import validate_capture

ROLL_NO_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")
WINDOW_NAME = "Enrollment - SPACE=capture  ESC=cancel"


def validate_roll_no(roll_no: str) -> str:
    roll_no = roll_no.strip()
    if not ROLL_NO_PATTERN.match(roll_no):
        raise ValueError(
            f"ID '{roll_no}' contains invalid characters (letters, numbers, hyphens and underscores allowed)"
        )
    return roll_no


def upsert_student(conn, roll_no: str, name: str, team_name: str | None = None, photo_path: str | None = None, **kwargs) -> None:
    """Insert or update a hackathon participant."""
    team = team_name or "Unassigned"
    existing = conn.execute("SELECT roll_no FROM students WHERE roll_no=?", (roll_no,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE students SET name=?, team_name=?, photo_path=COALESCE(?, photo_path) WHERE roll_no=?",
            (name, team, photo_path, roll_no),
        )
    else:
        conn.execute(
            "INSERT INTO students (roll_no, name, team_name, photo_path) VALUES (?,?,?,?)",
            (roll_no, name, team, photo_path),
        )
    conn.commit()


def run_enrollment(roll_no: str, name: str, year: int = 1, department: str = "IT", team_name: str | None = None) -> bool:
    app = get_face_app()

    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    if not cap.isOpened():
        print(f"ERROR: could not open camera index {CAMERA_INDEX}")
        return False

    captured = []  # (angle_label, embedding, photo_path)
    angle_idx = 0

    try:
        while angle_idx < len(ENROLLMENT_ANGLE_LABELS):
            angle_label = ENROLLMENT_ANGLE_LABELS[angle_idx]
            ret, frame = cap.read()
            if not ret:
                print("ERROR: camera read failed")
                break

            display = frame.copy()
            cv2.putText(
                display,
                f"Angle: {angle_label} ({angle_idx + 1}/{len(ENROLLMENT_ANGLE_LABELS)})  SPACE=capture  ESC=cancel",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )
            if captured:
                cv2.putText(
                    display,
                    f"Last: OK ({captured[-1][0]}, sharpness={captured[-1][3]:.0f})",
                    (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 200, 0),
                    1,
                )
            cv2.imshow(WINDOW_NAME, display)
            key = cv2.waitKey(1) & 0xFF

            if key == 27:  # ESC
                print("Cancelled by user — nothing saved.")
                return False

            if key == 32:  # SPACE
                faces = app.get(frame)
                result = validate_capture(frame, faces)
                if not result.ok:
                    print(f"[REJECTED] {angle_label}: {result.reason}")
                    continue

                embedding = result.face.normed_embedding.astype(np.float32)
                photo_path = ENROLLMENT_PHOTOS_DIR / f"{roll_no}_{angle_label}_{int(time.time())}.jpg"
                cv2.imwrite(str(photo_path), frame)
                captured.append((angle_label, embedding, str(photo_path), result.sharpness))
                print(
                    f"[OK] Captured '{angle_label}' "
                    f"({len(captured)}/{len(ENROLLMENT_ANGLE_LABELS)}, sharpness={result.sharpness:.0f})"
                )
                angle_idx += 1
    finally:
        cap.release()
        cv2.destroyAllWindows()

    if not captured:
        print("No captures — aborting enrollment.")
        return False

    conn = get_connection()
    try:
        upsert_student(conn, roll_no, name, year, department, team_name)
        for angle_label, embedding, _photo_path, _sharpness in captured:
            conn.execute(
                "INSERT INTO embeddings (roll_no, embedding, angle_label) VALUES (?,?,?)",
                (roll_no, embedding.tobytes(), angle_label),
            )
        conn.commit()
    finally:
        conn.close()

    print(f"Enrolled {roll_no} ({name}, Team: {team_name or 'N/A'}) with {len(captured)} embeddings.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Enroll a participant for face recognition attendance")
    parser.add_argument("--roll_no", required=True, help="e.g. 23it112 or P101")
    parser.add_argument("--name", required=True)
    parser.add_argument("--team_name", default=None, help="Team name")
    parser.add_argument("--year", type=int, default=1, choices=[1, 2, 3, 4])
    parser.add_argument("--department", default="IT")
    args = parser.parse_args()

    try:
        roll_no = validate_roll_no(args.roll_no)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    run_enrollment(roll_no, args.name.strip(), args.year, args.department.strip(), args.team_name)


if __name__ == "__main__":
    main()
