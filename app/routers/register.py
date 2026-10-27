"""Public self-registration for Hackathon participants: basic details entry before face capture."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from config import HACKATHON_TEAMS
from app.templating import templates
from db.connection import get_connection
from enrollment.enroll import validate_roll_no

router = APIRouter()


@router.get("/register")
def register_form(request: Request):
    conn = get_connection()
    try:
        existing_teams = [
            r["team_name"] for r in conn.execute(
                "SELECT DISTINCT team_name FROM students WHERE team_name != '' ORDER BY team_name"
            ).fetchall()
        ]
    finally:
        conn.close()

    return templates.TemplateResponse(request, "register.html", {
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
        "existing_teams": existing_teams,
        "hackathon_teams": HACKATHON_TEAMS,
    })


@router.get("/register/check")
def register_check(request: Request):
    roll_no = request.query_params.get("roll_no", "").strip()
    if not roll_no:
        return JSONResponse({"exists": False})

    conn = get_connection()
    try:
        row = conn.execute("SELECT 1 FROM students WHERE roll_no=?", (roll_no,)).fetchone()
    finally:
        conn.close()
    return JSONResponse({"exists": row is not None})


@router.post("/register")
async def register_submit(request: Request):
    form = await request.form()
    try:
        roll_no = validate_roll_no(form.get("roll_no", ""))
    except ValueError as e:
        return RedirectResponse(f"/register?error={e}", status_code=302)

    name = form.get("name", "").strip()
    team_name = form.get("team_name", "").strip()

    if not name:
        return RedirectResponse("/register?error=Full Name is required", status_code=302)
    if not team_name:
        return RedirectResponse("/register?error=Team Name is required", status_code=302)

    conn = get_connection()
    try:
        existing = conn.execute("SELECT 1 FROM students WHERE roll_no=?", (roll_no,)).fetchone()
        if existing is not None:
            return RedirectResponse(
                f"/register?error=Participant ID '{roll_no}' is already registered.", status_code=302
            )

        # Enforce max 4 members per team
        team_count = conn.execute(
            "SELECT COUNT(*) c FROM students WHERE team_name=?", (team_name,)
        ).fetchone()["c"]
        if team_count >= 4:
            return RedirectResponse(
                f"/register?error=Team '{team_name}' already has the maximum of 4 members", status_code=302
            )

        # Enforce max 30 teams
        total_teams = conn.execute(
            "SELECT COUNT(DISTINCT team_name) c FROM students WHERE team_name != '' AND team_name != ?",
            (team_name,)
        ).fetchone()["c"]
        if total_teams >= 30:
            return RedirectResponse(
                "/register?error=Maximum limit of 30 teams reached for the hackathon", status_code=302
            )

        conn.execute(
            "INSERT INTO students (roll_no, name, team_name) VALUES (?,?,?)",
            (roll_no, name, team_name),
        )
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(
        f"/register?success=Details saved for {name} ({roll_no}) in Team {team_name}. Please proceed to the event desk for face capture.",
        status_code=302,
    )
