"""Manage Shutdown Time: a global schedule of clock times at which every lab's
currently-IN students and faculty are auto-marked OUT — a scheduled, all-labs
version of the Scanner page's manual "Clear Lab" button. Admin-configured here;
actually applied by the background loop in `run_due_shutdowns()`, started from
app/main.py's startup hook."""

import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.deps import admin_template_context, require_main_admin
from app.templating import templates
from db.connection import get_connection

router = APIRouter()

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _current_period_id(conn) -> int | None:
    now = datetime.now().strftime("%H:%M")
    row = conn.execute(
        "SELECT id FROM periods WHERE start_time<=? AND end_time>=? LIMIT 1",
        (now, now),
    ).fetchone()
    return row["id"] if row else None


def run_due_shutdowns() -> None:
    """Check configured shutdown_times against the current clock time and, for
    any that match and haven't already fired today, mark every still-IN
    student and faculty (across all labs) as OUT. Safe to call repeatedly —
    each row only fires once per calendar day via last_triggered_date."""
    now_hhmm = datetime.now().strftime("%H:%M")
    today = date.today().isoformat()

    conn = get_connection()
    try:
        due = conn.execute(
            "SELECT * FROM shutdown_times WHERE time=? "
            "AND (last_triggered_date IS NULL OR last_triggered_date != ?)",
            (now_hhmm, today),
        ).fetchall()
        if not due:
            return

        now_iso = datetime.now().isoformat(sep=" ", timespec="seconds")
        period_id = _current_period_id(conn)

        for row in due:
            cur_students = conn.execute(
                "UPDATE attendance SET out_time=?, out_date=?, out_period_id=? "
                "WHERE out_time IS NULL",
                (now_iso, today, period_id),
            )
            cur_faculty = conn.execute(
                "UPDATE faculty_attendance SET out_time=?, out_date=?, out_period_id=? "
                "WHERE out_time IS NULL",
                (now_iso, today, period_id),
            )
            conn.execute(
                "UPDATE shutdown_times SET last_triggered_date=? WHERE id=?", (today, row["id"])
            )
            conn.commit()
            print(
                f"[shutdown-time] {row['time']} triggered: marked "
                f"{cur_students.rowcount} student(s) and {cur_faculty.rowcount} faculty OUT "
                "across all labs."
            )
    finally:
        conn.close()


@router.get("/shutdown-times")
def shutdown_times_list(request: Request):
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect

    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM shutdown_times ORDER BY time").fetchall()
    finally:
        conn.close()

    context = {
        **admin_template_context(user),
        "active_nav": "shutdown_times",
        "shutdown_times": rows,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    }
    return templates.TemplateResponse(request, "shutdown_times.html", context)


@router.post("/shutdown-times/add")
def shutdown_time_add(request: Request, time: str = Form(...)):
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect

    if not _TIME_RE.match(time):
        return RedirectResponse("/shutdown-times?error=Invalid time.", status_code=302)

    conn = get_connection()
    try:
        existing = conn.execute("SELECT 1 FROM shutdown_times WHERE time=?", (time,)).fetchone()
        if existing:
            return RedirectResponse(
                f"/shutdown-times?error={time} is already a configured shutdown time.",
                status_code=302,
            )
        conn.execute("INSERT INTO shutdown_times (time) VALUES (?)", (time,))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(f"/shutdown-times?success=Added shutdown time {time}.", status_code=302)


@router.post("/shutdown-times/{shutdown_id}/delete")
def shutdown_time_delete(request: Request, shutdown_id: int):
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect

    conn = get_connection()
    try:
        conn.execute("DELETE FROM shutdown_times WHERE id=?", (shutdown_id,))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/shutdown-times?success=Shutdown time removed.", status_code=302)
