"""Laptop Camera & Face Recognition Engine for 24-Hour Hackathon.

Strictly uses the local laptop webcam (Index 0).
Only runs when the user explicitly clicks "Start Camera", and releases the
camera hardware immediately when "Stop Camera" is clicked so the camera is
never on by default or running indefinitely in the background.
"""

import logging
import os
import threading
import time
from datetime import date, datetime, timedelta
from typing import Generator

import cv2
import numpy as np

from app import state
from config import CAMERA_INDEX, DEDUP_WINDOW_MINUTES
from db.connection import get_connection

logger = logging.getLogger("camera_stream")


def _toggle_attendance(
    conn, identity: str, lab_id: int, today: str
) -> tuple[str, bool]:
    """24-hour event IN/OUT toggle with dedup window and cross-midnight support.
    Automatically closes sessions in other venues if participant moves between the 3 halls."""
    now = datetime.now()
    now_str = now.isoformat(sep=" ", timespec="seconds")

    # If the participant has an unclosed session in ANY other venue, close that session first
    other_open = conn.execute(
        "SELECT id FROM attendance WHERE roll_no=? AND lab_id != ? AND out_time IS NULL",
        (identity, lab_id),
    ).fetchall()
    for row in other_open:
        conn.execute("UPDATE attendance SET out_time=?, out_date=? WHERE id=?", (now_str, today, row["id"]))

    # Look for an unclosed session in THIS venue
    unclosed = conn.execute(
        "SELECT * FROM attendance WHERE roll_no=? AND lab_id=? AND out_time IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (identity, lab_id),
    ).fetchone()

    if unclosed is not None:
        try:
            in_dt = datetime.fromisoformat(unclosed["in_time"])
        except (ValueError, TypeError):
            in_dt = now - timedelta(hours=1)

        if now - in_dt < timedelta(minutes=DEDUP_WINDOW_MINUTES):
            return "in", False

        conn.execute(
            "UPDATE attendance SET out_time=?, out_date=? WHERE id=?",
            (now_str, today, unclosed["id"]),
        )
        conn.commit()
        return "out", True

    # Check rapid re-scan after marking OUT
    last = conn.execute(
        "SELECT * FROM attendance WHERE roll_no=? AND lab_id=? ORDER BY id DESC LIMIT 1",
        (identity, lab_id),
    ).fetchone()

    if last is not None and last["out_time"] is not None:
        try:
            out_dt = datetime.fromisoformat(last["out_time"])
            if now - out_dt < timedelta(minutes=DEDUP_WINDOW_MINUTES):
                return "out", False
        except (ValueError, TypeError):
            pass

    # Start fresh IN session
    conn.execute(
        "INSERT INTO attendance (roll_no, lab_id, session_date, in_time) VALUES (?,?,?,?)",
        (identity, lab_id, today, now_str),
    )
    conn.commit()
    return "in", True


class LaptopCameraStreamManager:
    def __init__(self):
        self.cap: cv2.VideoCapture | None = None
        self.lock = threading.Lock()
        self.running = False

        # Latest frame and frame update notification
        self.latest_frame: np.ndarray | None = None
        self.frame_event = threading.Event()

        # Threads
        self._capture_thread: threading.Thread | None = None
        self._ai_thread: threading.Thread | None = None

        # Face recognition state
        self.latest_results: list[dict] = []
        self.last_results_time: float = 0
        self.last_event: dict | None = None
        self.last_event_time: float = 0
        self.default_lab_id: int | None = None

    def set_default_lab_id(self, lab_id: int | None) -> None:
        with self.lock:
            self.default_lab_id = lab_id

    def start(self, timeout: float = 3.5) -> bool:
        """Starts laptop camera hardware only on explicit demand.
        Blocks until the camera hardware is open and capturing frames before returning."""
        if self.running and self.latest_frame is not None:
            return True
        self.running = True

        if self._capture_thread is None or not self._capture_thread.is_alive():
            self._capture_thread = threading.Thread(
                target=self._capture_worker, daemon=True, name="LaptopCameraCaptureWorker"
            )
            self._capture_thread.start()

        if self._ai_thread is None or not self._ai_thread.is_alive():
            self._ai_thread = threading.Thread(
                target=self._ai_worker, daemon=True, name="LaptopCameraAIWorker"
            )
            self._ai_thread.start()

        print("Laptop Camera & Face Recognition pipelines started on demand.")

        # Wait until first frame is ready so video feed has immediate content
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if self.latest_frame is not None:
                    print("Laptop camera first frame acquired successfully!")
                    return True
            time.sleep(0.05)

        return self.running

    def stop(self) -> None:
        """Stops and releases the laptop webcam hardware immediately."""
        self.running = False
        self.frame_event.set()
        with self.lock:
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
            self.latest_frame = None
            self.latest_results = []
            self.last_event = None
        print("Laptop camera stopped and hardware released (LED off).")

    def _open_camera(self) -> cv2.VideoCapture | None:
        """Exclusively opens the laptop/local webcam with DirectShow and default fallback."""
        indices = [CAMERA_INDEX]
        if CAMERA_INDEX != 0:
            indices.append(0)
        elif CAMERA_INDEX != 1:
            indices.append(1)

        for idx in indices:
            # 1. Try DirectShow (fastest on Windows)
            try:
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                if cap.isOpened():
                    ret, test_frame = cap.read()
                    if ret and test_frame is not None:
                        print(f"DirectShow camera opened on index {idx}!")
                        return cap
                    cap.release()
            except Exception:
                pass

            # 2. Try Default Backend
            try:
                cap = cv2.VideoCapture(idx)
                if cap.isOpened():
                    ret, test_frame = cap.read()
                    if ret and test_frame is not None:
                        print(f"Default camera backend opened on index {idx}!")
                        return cap
                    cap.release()
            except Exception:
                pass

        return None

    def _capture_worker(self) -> None:
        """Hardware grabber: pulls raw frames with zero buffering."""
        try:
            while self.running:
                if self.cap is None or not self.cap.isOpened():
                    self.cap = self._open_camera()

                    if self.cap is not None and self.cap.isOpened():
                        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                        print("Laptop camera opened successfully!")
                    else:
                        print("Laptop camera not available, will retry in 1s...")
                        time.sleep(1)
                        continue

                # Read frame
                try:
                    ret, frame = self.cap.read()
                except Exception:
                    ret, frame = False, None

                if not ret or frame is None:
                    if self.running:
                        print("Camera frame dropped, retrying...")
                    if self.cap is not None:
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                    self.cap = None
                    time.sleep(0.5)
                    continue

                with self.lock:
                    self.latest_frame = frame
                self.frame_event.set()
        finally:
            with self.lock:
                if self.cap is not None:
                    try:
                        self.cap.release()
                    except Exception:
                        pass
                    self.cap = None

    def _ai_worker(self) -> None:
        """Asynchronous AI recognition worker."""
        while self.running:
            frame_to_process = None
            with self.lock:
                if self.latest_frame is not None:
                    frame_to_process = self.latest_frame.copy()

            if frame_to_process is None:
                time.sleep(0.02)
                continue

            orig_h, orig_w = frame_to_process.shape[:2]
            target_w = 640
            target_h = int(orig_h * (target_w / orig_w))
            small_frame = cv2.resize(frame_to_process, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

            scale_x = orig_w / target_w
            scale_y = orig_h / target_h

            try:
                recognizer = state.get_recognizer()
                results, _ = recognizer.recognize(small_frame)
            except Exception:
                time.sleep(0.05)
                continue

            for f in results:
                bbox = f.get("bbox")
                if bbox and len(bbox) == 4:
                    f["bbox"] = [
                        int(bbox[0] * scale_x),
                        int(bbox[1] * scale_y),
                        int(bbox[2] * scale_x),
                        int(bbox[3] * scale_y),
                    ]

            with self.lock:
                self.latest_results = results
                self.last_results_time = time.time()

            matched = next((f for f in results if f.get("identity") != "unknown"), None)
            if matched is None:
                unknown = next((f for f in results if f.get("identity") == "unknown"), None)
                if unknown:
                    now = time.time()
                    if (now - self.last_event_time) > 2.0:
                        self.last_event = {
                            "name": "unknown",
                            "identity": "unknown",
                            "kind": None,
                            "timestamp": now,
                        }
                        self.last_event_time = now
                continue

            identity = matched["identity"]
            conn = get_connection()
            try:
                person = conn.execute(
                    "SELECT name, COALESCE(team_name, 'No Team') AS team_name FROM students WHERE roll_no=?",
                    (identity,),
                ).fetchone()

                if person is None:
                    continue

                display_name = person["name"]
                team_name = person["team_name"]

                with self.lock:
                    target_lab_id = self.default_lab_id

                if target_lab_id is None:
                    first_lab = conn.execute("SELECT id FROM labs ORDER BY id ASC LIMIT 1").fetchone()
                    target_lab_id = first_lab["id"] if first_lab else 1

                today = date.today().isoformat()
                status, changed = _toggle_attendance(conn, identity, target_lab_id, today)

                now = time.time()
                if (
                    self.last_event is None
                    or self.last_event.get("identity") != identity
                    or (now - self.last_event_time) > 2.5
                ):
                    self.last_event = {
                        "name": display_name,
                        "team_name": team_name,
                        "identity": identity,
                        "kind": "student",
                        "status": status,
                        "marked": changed,
                        "timestamp": now,
                    }
                    self.last_event_time = now
            finally:
                conn.close()

            time.sleep(0.04)

    def _draw_annotations(self, frame: np.ndarray, results: list[dict]) -> np.ndarray:
        display = frame.copy()
        for f in results:
            bbox = f.get("bbox")
            if not bbox:
                continue
            x1, y1, x2, y2 = bbox
            known = f.get("identity") != "unknown"
            color = (0, 200, 0) if known else (0, 0, 255)

            cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
            label = f"{f.get('identity')} ({f.get('confidence', 0):.2f})" if known else "Unknown"

            (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
            label_y = max(lh + 8, y1 - 10)
            cv2.rectangle(display, (x1, label_y - lh - 6), (x1 + lw + 8, label_y + 4), color, -1)
            cv2.putText(
                display,
                label,
                (x1 + 4, label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

        return display

    def get_latest_event(self) -> dict | None:
        with self.lock:
            return self.last_event

    def generate_mjpeg(self) -> Generator[bytes, None, None]:
        """Streams live video with zero buffering while camera is active."""
        while self.running:
            time.sleep(0.04)
            if not self.running:
                break

            frame = None
            boxes = []
            now = time.time()

            with self.lock:
                if self.latest_frame is not None:
                    frame = self.latest_frame
                if (now - self.last_results_time) < 0.5:
                    boxes = list(self.latest_results)

            if frame is None:
                continue

            if boxes:
                annotated = self._draw_annotations(frame, boxes)
            else:
                annotated = frame

            success, buffer = cv2.imencode(
                ".jpg",
                annotated,
                [cv2.IMWRITE_JPEG_QUALITY, 68, cv2.IMWRITE_JPEG_OPTIMIZE, 0],
            )
            if not success:
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + buffer.tobytes()
                + b"\r\n"
            )


_stream_manager: LaptopCameraStreamManager | None = None


def get_stream_manager() -> LaptopCameraStreamManager:
    global _stream_manager
    if _stream_manager is None:
        _stream_manager = LaptopCameraStreamManager()
    return _stream_manager
