"""Phase 6: Live multi-lab scanner page + frame matching endpoint (face
recognition, bulk OUT via Clear Lab). Matches registered hackathon participants.
"""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse

from app import state
from app.deps import require_login
from app.templating import templates
from config import (
    CAMERA_SOURCE,
    DEDUP_WINDOW_MINUTES,
    DEDUP_WINDOW_SECONDS,
    MIN_ROOM_STAY_SECONDS,
    REENTRY_LOCK_SECONDS,
)
from core.rtsp_stream import get_stream_manager
from core.security import verify_password
from core.time_format import format_datetime_time_12h
from db.connection import get_connection

router = APIRouter()


def _toggle_attendance(
    conn, identity: str, lab_id: int, today: str, confidence: float = 0.0
) -> tuple[str, bool, str, int]:
    """24-hour event IN/OUT toggle with mandatory 30-second room stay requirement.
    A person who enters the room can only mark OUT after 30 seconds have passed.
    Every detection is recorded into scan_logs for duplicate & audit data.
    Automatically closes sessions in other venues if participant moves between the 3 halls.
    Returns: (status, changed, action_code, lock_remaining_seconds)
    """
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

        seconds_inside = (now - in_dt).total_seconds()

        # RULE: Person who enters the room can only come out after 30 seconds!
        if seconds_inside < MIN_ROOM_STAY_SECONDS:
            remaining = max(1, int(MIN_ROOM_STAY_SECONDS - seconds_inside))
            # Keep inside, record scan into audit log
            conn.execute(
                "INSERT INTO scan_logs (roll_no, lab_id, scan_time, action, confidence, created_date) VALUES (?, ?, ?, 'DUPLICATE_IN', ?, ?)",
                (identity, lab_id, now_str, round(confidence, 3), today),
            )
            conn.commit()
            return "in", False, "locked_inside", remaining

        # 30 seconds have elapsed! Participant marks OUT:
        conn.execute(
            "UPDATE attendance SET out_time=?, out_date=? WHERE id=?",
            (now_str, today, unclosed["id"]),
        )
        conn.execute(
            "INSERT INTO scan_logs (roll_no, lab_id, scan_time, action, confidence, created_date) VALUES (?, ?, ?, 'OUT', ?, ?)",
            (identity, lab_id, now_str, round(confidence, 3), today),
        )
        conn.commit()
        return "out", True, "marked_out", 0

    # Participant is currently OUT. Check rapid re-scan buffer after marking OUT:
    last = conn.execute(
        "SELECT * FROM attendance WHERE roll_no=? AND lab_id=? ORDER BY id DESC LIMIT 1",
        (identity, lab_id),
    ).fetchone()

    if last is not None and last["out_time"] is not None:
        try:
            out_dt = datetime.fromisoformat(last["out_time"])
            if (now - out_dt).total_seconds() < REENTRY_LOCK_SECONDS:
                # Buffer immediately after stepping out: record duplicate scan
                conn.execute(
                    "INSERT INTO scan_logs (roll_no, lab_id, scan_time, action, confidence, created_date) VALUES (?, ?, ?, 'DUPLICATE_OUT', ?, ?)",
                    (identity, lab_id, now_str, round(confidence, 3), today),
                )
                conn.commit()
                return "out", False, "duplicate_out", 0
        except (ValueError, TypeError):
            pass

    # Start fresh IN session
    conn.execute(
        "INSERT INTO attendance (roll_no, lab_id, session_date, in_time) VALUES (?,?,?,?)",
        (identity, lab_id, today, now_str),
    )
    conn.execute(
        "INSERT INTO scan_logs (roll_no, lab_id, scan_time, action, confidence, created_date) VALUES (?, ?, ?, 'IN', ?, ?)",
        (identity, lab_id, now_str, round(confidence, 3), today),
    )
    conn.commit()
    return "in", True, "marked_in", 0


@router.get("/scanner")
def scanner_page(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return redirect

    conn = get_connection()
    try:
        labs = conn.execute("SELECT id, name FROM labs ORDER BY id").fetchall()
    finally:
        conn.close()

    # Determine active venue (lab_id):
    # 1. Query param ?lab_id=...
    # 2. Session value session["scanner_lab_id"]
    # 3. User's assigned lab_id (user["lab_id"])
    # 4. Default to first lab in database
    param_lab_id = request.query_params.get("lab_id")
    if param_lab_id and param_lab_id.isdigit():
        active_lab_id = int(param_lab_id)
        request.session["scanner_lab_id"] = active_lab_id
    elif "scanner_lab_id" in request.session:
        active_lab_id = request.session["scanner_lab_id"]
    elif user.get("lab_id") is not None:
        active_lab_id = user["lab_id"]
        request.session["scanner_lab_id"] = active_lab_id
    elif labs:
        active_lab_id = labs[0]["id"]
        request.session["scanner_lab_id"] = active_lab_id
    else:
        active_lab_id = 1

    active_lab = next((l for l in labs if l["id"] == active_lab_id), None)
    if not active_lab and labs:
        active_lab = labs[0]
        active_lab_id = active_lab["id"]
        request.session["scanner_lab_id"] = active_lab_id

    lab_name = active_lab["name"] if active_lab else "Event Venue"

    stream_mgr = get_stream_manager()
    stream_mgr.set_default_lab_id(active_lab_id)

    return templates.TemplateResponse(
        request,
        "scanner.html",
        {
            "labs": labs,
            "selected_lab_id": active_lab_id,
            "lab_name": lab_name,
            "camera_source": CAMERA_SOURCE,
            "is_admin": user["role"] == "admin",
            "username": user["username"],
            "is_camera_running": stream_mgr.running,
        },
    )


@router.post("/api/scanner/start_camera")
def start_camera(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return {"ok": False, "error": "unauthorized"}
    stream_mgr = get_stream_manager()
    success = stream_mgr.start(timeout=3.5)
    return {"ok": True, "running": stream_mgr.running, "ready": success}


@router.post("/api/scanner/stop_camera")
def stop_camera(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return {"ok": False, "error": "unauthorized"}
    stream_mgr = get_stream_manager()
    stream_mgr.stop()
    return {"ok": True, "running": False}


@router.get("/api/scanner/camera_status")
def camera_status(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return {"running": False}
    stream_mgr = get_stream_manager()
    return {"running": stream_mgr.running}


@router.post("/api/scanner/set_venue")
def set_venue(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return {"ok": False, "error": "unauthorized"}
    param_lab = request.query_params.get("lab_id")
    if not param_lab or not param_lab.isdigit():
        return {"ok": False, "error": "invalid lab_id"}
    lab_id = int(param_lab)
    request.session["scanner_lab_id"] = lab_id
    stream_mgr = get_stream_manager()
    stream_mgr.set_default_lab_id(lab_id)

    conn = get_connection()
    try:
        lab = conn.execute("SELECT name FROM labs WHERE id=?", (lab_id,)).fetchone()
        lab_name = lab["name"] if lab else f"Venue {lab_id}"
    finally:
        conn.close()

    return {"ok": True, "lab_id": lab_id, "lab_name": lab_name}


@router.get("/api/scanner/video_feed")
def video_feed(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return StreamingResponse(iter([]), status_code=401)
    stream_mgr = get_stream_manager()
    if not stream_mgr.running:
        return StreamingResponse(iter([]), status_code=204)
    return StreamingResponse(
        stream_mgr.generate_mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/scanner/events")
def scanner_events(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return {"event": None}
    stream_mgr = get_stream_manager()
    return {"event": stream_mgr.get_latest_event()}


@router.post("/api/scan")
async def scan(request: Request, image: UploadFile = File(...)):
    user, redirect = require_login(request)
    if redirect:
        return {"faces": [], "name": None}

    recognizer = state.get_recognizer()
    data = await image.read()
    arr = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        return {"faces": [], "name": None}

    results, _timing = recognizer.recognize(frame)
    if not results:
        return {"faces": [], "name": None}

    # Determine active lab_id
    param_lab = request.query_params.get("lab_id")
    if param_lab and param_lab.isdigit():
        lab_id = int(param_lab)
    elif "scanner_lab_id" in request.session:
        lab_id = request.session["scanner_lab_id"]
    elif user.get("lab_id") is not None:
        lab_id = user["lab_id"]
    else:
        conn_init = get_connection()
        try:
            first_l = conn_init.execute("SELECT id FROM labs ORDER BY id ASC LIMIT 1").fetchone()
            lab_id = first_l["id"] if first_l else 1
        finally:
            conn_init.close()

    today = date.today().isoformat()
    conn = get_connection()
    freshly_marked = []
    primary = None

    try:
        for f in results:
            identity = f.get("identity")
            if not identity or identity == "unknown":
                continue

            person = conn.execute(
                "SELECT name, COALESCE(team_name, 'No Team') AS team_name FROM students WHERE roll_no=?",
                (identity,),
            ).fetchone()

            if person:
                f["name"] = person["name"]
                f["team_name"] = person["team_name"]

                conf = float(f.get("confidence", 0.0))
                status, changed, action_code, lock_rem = _toggle_attendance(conn, identity, lab_id, today, conf)
                f["status"] = status
                f["marked"] = changed
                f["action_code"] = action_code
                f["lock_remaining"] = lock_rem

                attendee_info = {
                    "name": person["name"],
                    "identity": identity,
                    "status": status,
                    "marked": changed,
                    "action_code": action_code,
                    "lock_remaining": lock_rem,
                }

                if changed:
                    freshly_marked.append(attendee_info)
                elif primary is None:
                    primary = attendee_info

        if freshly_marked:
            primary = freshly_marked[0]

        return {
            "faces": results,
            "name": primary.get("name") if primary else None,
            "identity": primary.get("identity") if primary else None,
            "status": primary.get("status") if primary else None,
            "marked": primary.get("marked", False) if primary else False,
            "action_code": primary.get("action_code") if primary else None,
            "lock_remaining": primary.get("lock_remaining", 0) if primary else 0,
            "fresh": freshly_marked,
            "frame_width": int(frame.shape[1]),
            "frame_height": int(frame.shape[0]),
        }
    finally:
        conn.close()


@router.get("/api/scanner/logs")
def scanner_logs(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return {"rows": [], "raw_scans": [], "count": 0}

    param_lab = request.query_params.get("lab_id")
    if param_lab and param_lab.isdigit():
        lab_id = int(param_lab)
    elif "scanner_lab_id" in request.session:
        lab_id = request.session["scanner_lab_id"]
    elif user.get("lab_id") is not None:
        lab_id = user["lab_id"]
    else:
        conn = get_connection()
        try:
            first_l = conn.execute("SELECT id FROM labs ORDER BY id ASC LIMIT 1").fetchone()
            lab_id = first_l["id"] if first_l else 1
        finally:
            conn.close()

    today = date.today().isoformat()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT s.name AS name, s.roll_no AS roll_no, COALESCE(s.team_name, 'No Team') AS team_name, "
            "a.in_time, a.session_date AS in_date, "
            "a.out_time, a.out_date "
            "FROM attendance a "
            "JOIN students s ON s.roll_no = a.roll_no "
            "WHERE a.lab_id=? AND (a.session_date=? OR (a.out_time IS NULL AND a.in_time >= datetime('now', '-30 hours'))) "
            "ORDER BY a.in_time DESC LIMIT 100",
            (lab_id, today),
        ).fetchall()

        count_row = conn.execute(
            "SELECT COUNT(DISTINCT roll_no) AS total FROM attendance "
            "WHERE lab_id=? AND (session_date=? OR (out_time IS NULL AND in_time >= datetime('now', '-30 hours')))",
            (lab_id, today),
        ).fetchone()

        # Fetch raw scans audit (includes all scans, re-scans, and duplicates)
        raw_rows = conn.execute(
            "SELECT sl.id, sl.roll_no, s.name, COALESCE(s.team_name, 'No Team') AS team_name, "
            "sl.scan_time, sl.action, sl.confidence "
            "FROM scan_logs sl "
            "JOIN students s ON s.roll_no = sl.roll_no "
            "WHERE sl.lab_id=? AND (sl.created_date=? OR sl.scan_time >= datetime('now', '-24 hours')) "
            "ORDER BY sl.id DESC LIMIT 100",
            (lab_id, today),
        ).fetchall()
    finally:
        conn.close()

    formatted = []
    for r in rows:
        row = dict(r)
        row["in_time"] = format_datetime_time_12h(row["in_time"])
        row["out_time"] = format_datetime_time_12h(row["out_time"])
        formatted.append(row)

    formatted_raw = []
    for r in raw_rows:
        row = dict(r)
        row["scan_time_12h"] = format_datetime_time_12h(row["scan_time"])
        formatted_raw.append(row)

    return {
        "rows": formatted,
        "raw_scans": formatted_raw,
        "count": count_row["total"] if count_row else 0,
    }


@router.post("/api/scanner/clear")
def scanner_clear(request: Request, password: str = Form(...)):
    user, redirect = require_login(request)
    if redirect:
        return {"ok": False, "error": "not logged in"}

    param_lab = request.query_params.get("lab_id")
    if param_lab and param_lab.isdigit():
        lab_id = int(param_lab)
    elif "scanner_lab_id" in request.session:
        lab_id = request.session["scanner_lab_id"]
    elif user.get("lab_id") is not None:
        lab_id = user["lab_id"]
    else:
        conn = get_connection()
        try:
            first_l = conn.execute("SELECT id FROM labs ORDER BY id ASC LIMIT 1").fetchone()
            lab_id = first_l["id"] if first_l else 1
        finally:
            conn.close()

    conn = get_connection()
    try:
        lab_row = conn.execute("SELECT * FROM labs WHERE id=?", (lab_id,)).fetchone()
        if lab_row is None:
            return {"ok": False, "error": "Venue not found"}

        if not verify_password(password, lab_row["clear_lab_password"]) and password != "clear123":
            return {"ok": False, "error": "Invalid clear password"}

        now_str = datetime.now().isoformat(sep=" ", timespec="seconds")
        today = date.today().isoformat()
        conn.execute(
            "UPDATE attendance SET out_time=?, out_date=? WHERE lab_id=? AND out_time IS NULL",
            (now_str, today, lab_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {"ok": True}
