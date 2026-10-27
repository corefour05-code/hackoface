"""Phase 4: Manage Labs + Lab Security Configuration (clear-lab passwords).
Main-admin only (System Config).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from config import DEFAULT_CLEAR_LAB_PASSWORD
from core.security import hash_password
from db.connection import get_connection

from app.deps import admin_template_context, require_main_admin
from app.templating import templates

router = APIRouter()


def _labs_with_admin(conn):
    return conn.execute(
        "SELECT l.*, "
        "(SELECT u.username FROM users u WHERE u.lab_id = l.id AND u.role='admin' LIMIT 1) AS admin_username, "
        "(SELECT COUNT(DISTINCT roll_no) FROM attendance a WHERE a.lab_id = l.id AND a.out_time IS NULL) AS live_inside "
        "FROM labs l ORDER BY l.id"
    ).fetchall()


@router.get("/labs")
def labs_list(request: Request):
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect
    conn = get_connection()
    try:
        labs = _labs_with_admin(conn)
    finally:
        conn.close()
    context = {**admin_template_context(user), "active_nav": "labs", "labs": labs}
    return templates.TemplateResponse(request, "labs_list.html", context)


@router.get("/labs/create")
def lab_create_form(request: Request):
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect
    context = {
        **admin_template_context(user),
        "active_nav": "labs",
        "default_clear_password": DEFAULT_CLEAR_LAB_PASSWORD,
    }
    return templates.TemplateResponse(request, "lab_create.html", context)


@router.post("/labs/create")
def lab_create_submit(
    request: Request,
    name: str = Form(...),
    admin_username: str = Form(...),
    admin_password: str = Form(...),
    clear_password: str = Form(DEFAULT_CLEAR_LAB_PASSWORD),
):
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE username=?", (admin_username,)
        ).fetchone()
        if existing:
            return RedirectResponse(
                f"/labs/create?error=Username '{admin_username}' already exists", status_code=302
            )

        cur = conn.execute(
            "INSERT INTO labs (name, clear_lab_password) VALUES (?,?)",
            (name.strip(), clear_password.strip() or DEFAULT_CLEAR_LAB_PASSWORD),
        )
        lab_id = cur.lastrowid
        conn.execute(
            "INSERT INTO users (username, password_hash, role, lab_id) VALUES (?,?,?,?)",
            (admin_username.strip(), hash_password(admin_password), "admin", lab_id),
        )
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(f"/labs?success=Created lab '{name}'", status_code=302)


@router.post("/labs/{lab_id}/edit")
def lab_edit_submit(request: Request, lab_id: int, name: str = Form(...)):
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect

    new_name = name.strip()
    if not new_name:
        return RedirectResponse("/labs?error=Venue name cannot be empty", status_code=302)

    conn = get_connection()
    try:
        conn.execute("UPDATE labs SET name=? WHERE id=?", (new_name, lab_id))
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(f"/labs?success=Venue renamed to '{new_name}'", status_code=302)


@router.post("/labs/{lab_id}/delete")
def lab_delete(request: Request, lab_id: int):
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect

    conn = get_connection()
    try:
        # Delete lab-scoped users explicitly rather than relying on the FK's
        # ON DELETE SET NULL, which would otherwise silently promote them to
        # super-admin (lab_id=NULL means super-admin in this app's model).
        conn.execute("DELETE FROM users WHERE lab_id=?", (lab_id,))
        conn.execute("DELETE FROM labs WHERE id=?", (lab_id,))
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse("/labs?success=Lab deleted", status_code=302)


@router.get("/lab-security")
def lab_security(request: Request):
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect
    conn = get_connection()
    try:
        labs = conn.execute("SELECT * FROM labs ORDER BY name").fetchall()
    finally:
        conn.close()
    context = {**admin_template_context(user), "active_nav": "lab_security", "labs": labs}
    return templates.TemplateResponse(request, "lab_security.html", context)


@router.post("/lab-security/{lab_id}")
def lab_security_save(request: Request, lab_id: int, clear_lab_password: str = Form(...)):
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE labs SET clear_lab_password=? WHERE id=?", (clear_lab_password.strip(), lab_id)
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/lab-security?success=Saved", status_code=302)
