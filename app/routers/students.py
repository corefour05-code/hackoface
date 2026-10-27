"""Hackathon Participants management: Add, Edit, Delete with face capture and max 4 members / team validation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app import state
from app.deps import admin_template_context, require_main_admin
from app.templating import templates
from config import HACKATHON_TEAMS
from core.image_utils import decode_data_url
from db.connection import get_connection
from enrollment.enroll import upsert_student, validate_roll_no

router = APIRouter()


def _collect_photo_data_urls(form) -> list[str]:
    urls = []
    i = 1
    while True:
        val = form.get(f"photo_{i}")
        if not val:
            break
        urls.append(val)
        i += 1
    return urls


def _save_embeddings(conn, roll_no: str, data_urls: list[str]) -> int:
    recognizer = state.get_recognizer()
    saved = 0
    for data_url in data_urls:
        try:
            frame = decode_data_url(data_url)
        except ValueError:
            continue
        faces = recognizer.app.get(frame)
        if not faces:
            continue
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        embedding = face.normed_embedding.astype(np.float32)
        conn.execute(
            "INSERT INTO embeddings (roll_no, embedding, angle_label) VALUES (?,?,?)",
            (roll_no, embedding.tobytes(), f"shot_{saved + 1}"),
        )
        saved += 1
    return saved


def _rename_roll_no(conn, old_roll_no: str, new_roll_no: str) -> None:
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("UPDATE students SET roll_no=? WHERE roll_no=?", (new_roll_no, old_roll_no))
        conn.execute("UPDATE embeddings SET roll_no=? WHERE roll_no=?", (new_roll_no, old_roll_no))
        conn.execute("UPDATE attendance SET roll_no=? WHERE roll_no=?", (new_roll_no, old_roll_no))
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _students_list_response(request: Request, user, intent: str | None, active_nav: str, list_path: str):
    q = request.query_params.get("q", "").strip()
    team_name = request.query_params.get("team_name", "").strip()

    sql = "SELECT s.*, (SELECT COUNT(*) FROM embeddings e WHERE e.roll_no = s.roll_no) AS embedding_count FROM students s WHERE 1=1"
    params: list = []
    if q:
        sql += " AND (s.roll_no LIKE ? OR s.name LIKE ? OR s.team_name LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if team_name:
        sql += " AND s.team_name = ?"
        params.append(team_name)
    sql += " ORDER BY s.team_name, s.roll_no"

    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        team_stats = conn.execute(
            "SELECT team_name, COUNT(*) AS member_count FROM students WHERE team_name != '' GROUP BY team_name ORDER BY team_name"
        ).fetchall()
        teams = [r["team_name"] for r in team_stats]
        team_member_counts = {r["team_name"]: r["member_count"] for r in team_stats}
    finally:
        conn.close()

    context = {
        **admin_template_context(user),
        "active_nav": active_nav,
        "students": rows,
        "q": q,
        "team_name": team_name,
        "teams": teams,
        "team_member_counts": team_member_counts,
        "intent": intent,
        "list_path": list_path,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
        "student_count": len(rows),
    }
    return templates.TemplateResponse(request, "students_list.html", context)


@router.get("/students/check-roll-no")
def check_roll_no(request: Request):
    user, redirect = require_main_admin(request)
    if redirect:
        return JSONResponse({"exists": False}, status_code=403)

    roll_no = request.query_params.get("roll_no", "").strip()
    if not roll_no:
        return {"exists": False}

    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM students WHERE roll_no=?", (roll_no,)).fetchone()
        embedding_count = 0
        if row is not None:
            embedding_count = conn.execute(
                "SELECT COUNT(*) c FROM embeddings WHERE roll_no=?", (roll_no,)
            ).fetchone()["c"]
    finally:
        conn.close()

    if row is None:
        return {"exists": False}
    return {
        "exists": True,
        "name": row["name"],
        "team_name": row["team_name"] or "",
        "embedding_count": embedding_count,
        "has_embeddings": embedding_count > 0,
    }


@router.get("/students")
def students_list(request: Request):
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect
    return _students_list_response(request, user, None, "students", "/students")


@router.get("/students/add")
def student_add_form(request: Request):
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect

    conn = get_connection()
    try:
        existing_teams = [
            r["team_name"] for r in conn.execute(
                "SELECT DISTINCT team_name FROM students WHERE team_name != '' ORDER BY team_name"
            ).fetchall()
        ]
    finally:
        conn.close()

    context = {
        **admin_template_context(user),
        "active_nav": "student_add",
        "mode": "add",
        "student": None,
        "existing_teams": existing_teams,
        "hackathon_teams": HACKATHON_TEAMS,
        "error": request.query_params.get("error"),
    }
    return templates.TemplateResponse(request, "student_form.html", context)


@router.post("/students/add")
async def student_add_submit(request: Request):
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect

    form = await request.form()
    try:
        roll_no = validate_roll_no(form.get("roll_no", ""))
    except ValueError as e:
        return RedirectResponse(f"/students/add?error={e}", status_code=302)

    name = form.get("name", "").strip()
    team_name = form.get("team_name", "").strip()

    if not name:
        return RedirectResponse("/students/add?error=Name is required", status_code=302)
    if not team_name:
        return RedirectResponse("/students/add?error=Team Name is required", status_code=302)

    photo_urls = _collect_photo_data_urls(form)
    if not photo_urls:
        return RedirectResponse("/students/add?error=At least one face photo capture is required", status_code=302)

    conn = get_connection()
    try:
        # Check if roll_no already exists
        exists = conn.execute("SELECT roll_no FROM students WHERE roll_no=?", (roll_no,)).fetchone()
        if exists:
            return RedirectResponse(f"/students/add?error=Participant ID '{roll_no}' already exists", status_code=302)

        # Enforce max 4 members per team
        team_count = conn.execute(
            "SELECT COUNT(*) c FROM students WHERE team_name=?", (team_name,)
        ).fetchone()["c"]
        if team_count >= 4:
            return RedirectResponse(
                f"/students/add?error=Team '{team_name}' already has the maximum of 4 members", status_code=302
            )

        # Enforce max 30 teams
        total_teams = conn.execute(
            "SELECT COUNT(DISTINCT team_name) c FROM students WHERE team_name != '' AND team_name != ?",
            (team_name,)
        ).fetchone()["c"]
        if total_teams >= 30:
            return RedirectResponse(
                "/students/add?error=Maximum limit of 30 teams has been reached", status_code=302
            )

        upsert_student(conn, roll_no, name, team_name)
        saved = _save_embeddings(conn, roll_no, photo_urls)
        conn.commit()
    finally:
        conn.close()

    state.get_recognizer().reload_embeddings()
    return RedirectResponse(
        f"/students?success=Successfully enrolled {name} ({roll_no}) in team {team_name} with {saved} face angles.", status_code=302
    )


@router.get("/students/{roll_no}/edit")
def student_edit_form(request: Request, roll_no: str):
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect

    conn = get_connection()
    try:
        student = conn.execute("SELECT * FROM students WHERE roll_no=?", (roll_no,)).fetchone()
        embedding_count = conn.execute(
            "SELECT COUNT(*) c FROM embeddings WHERE roll_no=?", (roll_no,)
        ).fetchone()["c"]
        existing_teams = [
            r["team_name"] for r in conn.execute(
                "SELECT DISTINCT team_name FROM students WHERE team_name != '' ORDER BY team_name"
            ).fetchall()
        ]
    finally:
        conn.close()

    if student is None:
        return RedirectResponse("/students?error=Participant not found", status_code=302)

    context = {
        **admin_template_context(user),
        "active_nav": "students",
        "mode": "edit",
        "student": student,
        "embedding_count": embedding_count,
        "existing_teams": existing_teams,
        "hackathon_teams": HACKATHON_TEAMS,
        "error": request.query_params.get("error"),
    }
    return templates.TemplateResponse(request, "student_form.html", context)


@router.post("/students/{roll_no}/edit")
async def student_edit_submit(request: Request, roll_no: str):
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect

    form = await request.form()
    name = form.get("name", "").strip()
    team_name = form.get("team_name", "").strip()

    try:
        new_roll_no = validate_roll_no(form.get("roll_no", roll_no))
    except ValueError as e:
        return RedirectResponse(f"/students/{roll_no}/edit?error={e}", status_code=302)

    if not name or not team_name:
        return RedirectResponse(f"/students/{roll_no}/edit?error=Name and Team Name are required", status_code=302)

    photo_urls = _collect_photo_data_urls(form)

    conn = get_connection()
    try:
        if new_roll_no != roll_no:
            collision = conn.execute("SELECT roll_no FROM students WHERE roll_no=?", (new_roll_no,)).fetchone()
            if collision:
                return RedirectResponse(
                    f"/students/{roll_no}/edit?error=ID '{new_roll_no}' already exists", status_code=302
                )
            _rename_roll_no(conn, roll_no, new_roll_no)

        # Enforce max 4 members on destination team
        team_count = conn.execute(
            "SELECT COUNT(*) c FROM students WHERE team_name=? AND roll_no != ?",
            (team_name, new_roll_no)
        ).fetchone()["c"]
        if team_count >= 4:
            return RedirectResponse(
                f"/students/{roll_no}/edit?error=Team '{team_name}' already has the maximum of 4 members", status_code=302
            )

        conn.execute(
            "UPDATE students SET name=?, team_name=? WHERE roll_no=?",
            (name, team_name, new_roll_no),
        )
        saved = 0
        if photo_urls:
            saved = _save_embeddings(conn, new_roll_no, photo_urls)
        conn.commit()
    finally:
        conn.close()

    if photo_urls or new_roll_no != roll_no:
        state.get_recognizer().reload_embeddings()

    return RedirectResponse(f"/students?success=Updated participant {new_roll_no} (Team {team_name}).", status_code=302)


@router.delete("/students/{roll_no}")
def student_delete(request: Request, roll_no: str):
    user, redirect = require_main_admin(request)
    if redirect:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=403)

    conn = get_connection()
    try:
        conn.execute("DELETE FROM students WHERE roll_no=?", (roll_no,))
        conn.commit()
    finally:
        conn.close()

    state.get_recognizer().reload_embeddings()
    return {"ok": True}
