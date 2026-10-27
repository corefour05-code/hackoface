"""Phase 7: filterable Venue Attendance Report + PDF export."""

import io
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import APIRouter, Request
from fastapi.responses import Response
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

from app.deps import admin_template_context, is_main_admin, require_admin
from app.templating import templates
from core.time_format import format_datetime_time_12h
from db.connection import get_connection

router = APIRouter()

REPORT_COLUMNS = [
    "S.No", "ID", "Name", "Team Name",
    "Venue", "In Time", "In Date", "Out Time", "Out Date",
]


def _build_filters(request: Request, user: dict):
    from_date = request.query_params.get("from_date") or date.today().isoformat()
    to_date = request.query_params.get("to_date") or date.today().isoformat()
    q = request.query_params.get("q", "").strip()
    team_name = request.query_params.get("team_name", "").strip()

    if is_main_admin(user):
        lab_id_param = request.query_params.get("lab_id")
        lab_id = int(lab_id_param) if lab_id_param else None
    else:
        lab_id = user["lab_id"]

    return from_date, to_date, lab_id, team_name, q


def _fetch_rows(conn, from_date, to_date, lab_id, team_name, q):
    student_sql = (
        "SELECT s.roll_no AS person_id, s.name AS name, COALESCE(s.team_name, 'No Team') AS team_name, "
        "l.id AS lab_id, l.name AS lab_name, "
        "a.in_time, a.session_date AS in_date, "
        "a.out_time, a.out_date "
        "FROM attendance a "
        "JOIN students s ON s.roll_no = a.roll_no "
        "JOIN labs l ON l.id = a.lab_id "
        "WHERE (a.session_date BETWEEN ? AND ?) OR (a.out_time IS NULL AND a.in_time >= datetime('now', '-30 hours'))"
    )
    student_params: list = [from_date, to_date]
    if lab_id is not None:
        student_sql += " AND a.lab_id = ?"
        student_params.append(lab_id)
    if team_name:
        student_sql += " AND s.team_name = ?"
        student_params.append(team_name)
    if q:
        student_sql += " AND (s.name LIKE ? OR s.roll_no LIKE ? OR s.team_name LIKE ?)"
        student_params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    student_sql += " ORDER BY a.in_time DESC"
    return conn.execute(student_sql, student_params).fetchall()


@router.get("/report")
def lab_report(request: Request):
    user, redirect = require_admin(request)
    if redirect:
        return redirect

    from_date, to_date, lab_id, team_name, q = _build_filters(request, user)

    conn = get_connection()
    try:
        rows = _fetch_rows(conn, from_date, to_date, lab_id, team_name, q)
        labs = conn.execute("SELECT * FROM labs ORDER BY name").fetchall()
        teams = [
            r["team_name"] for r in conn.execute(
                "SELECT DISTINCT team_name FROM students WHERE team_name IS NOT NULL AND team_name != '' ORDER BY team_name"
            ).fetchall()
        ]
        locked_lab_name = None
        if not is_main_admin(user) and user["lab_id"] is not None:
            lab_row = conn.execute("SELECT name FROM labs WHERE id=?", (user["lab_id"],)).fetchone()
            locked_lab_name = lab_row["name"] if lab_row else "Unknown Venue"
    finally:
        conn.close()

    unique_students = len({r["person_id"] for r in rows})
    team_counts: dict[str, int] = {}
    for r in rows:
        team = r["team_name"] or "No Team"
        team_counts[team] = team_counts.get(team, 0) + 1

    context = {
        **admin_template_context(user),
        "active_nav": "report",
        "rows": rows,
        "labs": labs,
        "teams": teams,
        "from_date": from_date,
        "to_date": to_date,
        "selected_lab_id": lab_id,
        "locked_lab_name": locked_lab_name,
        "team_name": team_name,
        "q": q,
        "query_string": request.url.query,
        "total_records": len(rows),
        "unique_students": unique_students,
        "team_counts": sorted(team_counts.items(), key=lambda kv: kv[1], reverse=True),
    }
    return templates.TemplateResponse(request, "report.html", context)


@router.get("/report/pdf")
def lab_report_pdf(request: Request):
    user, redirect = require_admin(request)
    if redirect:
        return redirect

    from_date, to_date, lab_id, team_name, q = _build_filters(request, user)

    conn = get_connection()
    try:
        rows = _fetch_rows(conn, from_date, to_date, lab_id, team_name, q)
    finally:
        conn.close()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
    styles = getSampleStyleSheet()

    data = [REPORT_COLUMNS]
    for i, r in enumerate(rows, start=1):
        data.append([
            str(i), r["person_id"], r["name"], r["team_name"] or "-",
            r["lab_name"],
            format_datetime_time_12h(r["in_time"]), r["in_date"] or "-",
            format_datetime_time_12h(r["out_time"]), r["out_date"] or "-",
        ])

    elements = [
        Paragraph(f"Venue Attendance Report ({from_date} to {to_date})", styles["Title"]),
    ]
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#077c3c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
    ]))
    elements.append(table)
    doc.build(elements)

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=attendance_report_{from_date}_to_{to_date}.pdf"},
    )
