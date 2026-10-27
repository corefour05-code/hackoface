"""Analytics & Master Event Timer for 24-Hour Hackathon Face Recognition Platform.

Features:
- Master Event Timer (24-hour clock: Start, Pause, Reset)
- Overall IN and OUT counts with real-time percentages
- Team-level presence percentage and Hall Endurance Leaderboard Ranking
- Individual member-level presence percentages and active venue tracking
- Filter by Team Name (showing team % and each member's %)
- Live Venue occupancy across the 3 editable venues
"""

import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.deps import admin_template_context, get_developers_context, require_main_admin
from app.templating import templates
from core.time_format import format_datetime_time_12h
from db.connection import get_connection

router = APIRouter()


def _format_duration(total_minutes: float) -> str:
    if total_minutes <= 0:
        return "0m"
    hours = int(total_minutes // 60)
    mins = int(total_minutes % 60)
    if hours > 0 and mins > 0:
        return f"{hours}h {mins}m"
    elif hours > 0:
        return f"{hours}h"
    return f"{mins}m"


def _parse_dt(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def get_event_timer(conn) -> dict:
    """Retrieve the current 24-hour master event timer status."""
    rows = conn.execute("SELECT key, value FROM event_config").fetchall()
    config = {r["key"]: r["value"] for r in rows}

    is_active = config.get("is_active") == "1"
    start_time_str = config.get("start_time", "")
    duration_hours = float(config.get("duration_hours", "24"))
    event_name = config.get("event_name", "PSNA IT 24-Hour Hackathon")

    now = datetime.now()
    start_dt = _parse_dt(start_time_str)

    if start_dt:
        elapsed_seconds = max(0, int((now - start_dt).total_seconds()))
    else:
        elapsed_seconds = 0

    total_event_seconds = int(duration_hours * 3600)
    remaining_seconds = max(0, total_event_seconds - elapsed_seconds)

    # Format strings
    el_h = elapsed_seconds // 3600
    el_m = (elapsed_seconds % 3600) // 60
    el_s = elapsed_seconds % 60
    elapsed_str = f"{el_h:02d}h {el_m:02d}m {el_s:02d}s"

    rem_h = remaining_seconds // 3600
    rem_m = (remaining_seconds % 3600) // 60
    remaining_str = f"{rem_h:02d}h {rem_m:02d}m"

    progress_pct = min(100.0, round((elapsed_seconds / total_event_seconds) * 100.0, 1)) if total_event_seconds > 0 else 0.0

    return {
        "event_name": event_name,
        "is_active": is_active,
        "has_started": start_dt is not None,
        "start_time": start_time_str,
        "duration_hours": duration_hours,
        "elapsed_seconds": elapsed_seconds,
        "elapsed_minutes": elapsed_seconds / 60.0,
        "elapsed_str": elapsed_str,
        "remaining_seconds": remaining_seconds,
        "remaining_str": remaining_str,
        "progress_pct": progress_pct,
    }


def _calculate_team_analytics(conn, from_date, to_date, lab_id=None, selected_team="", q="", status_filter="all", team_name=None):
    if team_name is not None and not selected_team:
        selected_team = team_name

    timer = get_event_timer(conn)
    event_elapsed_mins = timer["elapsed_minutes"]
    # If event has not started or just started (< 1 min), baseline is 1.0 minute
    effective_elapsed_mins = max(1.0, event_elapsed_mins) if timer["has_started"] else 0.0

    # 1. Fetch participants (max 30 teams, max 4 members)
    p_sql = "SELECT roll_no, name, COALESCE(NULLIF(team_name, ''), 'Unassigned') AS team_name FROM students WHERE 1=1"
    p_params = []
    if selected_team:
        p_sql += " AND team_name = ?"
        p_params.append(selected_team)
    if q:
        p_sql += " AND (roll_no LIKE ? OR name LIKE ? OR team_name LIKE ?)"
        p_params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    p_sql += " ORDER BY team_name, roll_no"
    participants = conn.execute(p_sql, p_params).fetchall()

    # 2. Fetch attendance sessions
    att_sql = (
        "SELECT a.id, a.roll_no, a.lab_id, l.name AS lab_name, a.session_date, "
        "a.in_time, a.out_time, a.out_date "
        "FROM attendance a "
        "JOIN labs l ON l.id = a.lab_id "
        "WHERE (a.session_date BETWEEN ? AND ?) OR (a.out_time IS NULL AND a.in_time >= datetime('now', '-30 hours'))"
    )
    att_params = [from_date, to_date]
    if lab_id is not None:
        att_sql += " AND a.lab_id = ?"
        att_params.append(lab_id)
    att_sql += " ORDER BY a.roll_no, a.in_time ASC"
    att_rows = conn.execute(att_sql, att_params).fetchall()

    user_sessions = defaultdict(list)
    for r in att_rows:
        user_sessions[r["roll_no"]].append(r)

    now = datetime.now()

    # 3. Analyze each participant
    analyzed_participants = []
    team_members = defaultdict(list)

    for p in participants:
        roll_no = p["roll_no"]
        name = p["name"]
        team = p["team_name"]

        sessions = user_sessions.get(roll_no, [])
        is_in = False
        current_venue = None
        latest_in = None
        latest_out = None
        total_mins = 0.0

        for s in sessions:
            in_dt = _parse_dt(s["in_time"])
            out_dt = _parse_dt(s["out_time"]) if s["out_time"] else None

            if in_dt:
                if latest_in is None or in_dt > latest_in:
                    latest_in = in_dt
                if out_dt:
                    if latest_out is None or out_dt > latest_out:
                        latest_out = out_dt
                    dur = max(0.0, (out_dt - in_dt).total_seconds() / 60.0)
                    total_mins += dur
                else:
                    # Still inside venue!
                    is_in = True
                    current_venue = s["lab_name"]
                    dur = max(0.0, (now - in_dt).total_seconds() / 60.0)
                    total_mins += dur

        # Calculate member presence percentage
        if effective_elapsed_mins > 0:
            member_pct = min(100.0, round((total_mins / effective_elapsed_mins) * 100.0, 1))
        elif is_in:
            member_pct = 100.0
        else:
            member_pct = 0.0

        total_out_mins = max(0.0, effective_elapsed_mins - total_mins)
        out_pct = round(max(0.0, 100.0 - member_pct), 1)

        # Detailed "When OUT" calculations for each member
        if not is_in:
            if latest_out:
                out_since_iso = latest_out.strftime("%Y-%m-%d %H:%M:%S")
                out_since_12h = format_datetime_time_12h(out_since_iso)
                cur_out_mins = max(0.0, (now - latest_out).total_seconds() / 60.0)
                cur_out_str = _format_duration(cur_out_mins)
                when_out_str = f"OUT since {out_since_12h} ({cur_out_str} ago)"
                when_out_short = f"Left at {out_since_12h}"
            else:
                out_since_iso = None
                out_since_12h = None
                cur_out_mins = effective_elapsed_mins
                cur_out_str = _format_duration(effective_elapsed_mins)
                when_out_str = "Not Yet Entered Venue"
                when_out_short = "Not Entered"
        else:
            in_since_iso = latest_in.strftime("%Y-%m-%d %H:%M:%S") if latest_in else None
            in_since_12h = format_datetime_time_12h(in_since_iso) if in_since_iso else None
            cur_in_mins = max(0.0, (now - latest_in).total_seconds() / 60.0) if latest_in else 0.0
            cur_in_str = _format_duration(cur_in_mins)
            when_out_str = f"Active Inside ({current_venue})"
            when_out_short = f"IN since {in_since_12h}"
            cur_out_mins = 0.0
            cur_out_str = "0m"
            out_since_iso = None
            out_since_12h = None

        # Filter by status if requested
        if status_filter == "in" and not is_in:
            continue
        if status_filter == "out" and is_in:
            continue

        p_info = {
            "roll_no": roll_no,
            "name": name,
            "team_name": team,
            "is_in": is_in,
            "current_venue": current_venue,
            "in_time": latest_in.strftime("%Y-%m-%d %H:%M:%S") if latest_in else None,
            "in_time_12h": format_datetime_time_12h(latest_in.strftime("%Y-%m-%d %H:%M:%S")) if latest_in else None,
            "out_time": latest_out.strftime("%Y-%m-%d %H:%M:%S") if latest_out else None,
            "out_time_12h": format_datetime_time_12h(latest_out.strftime("%Y-%m-%d %H:%M:%S")) if latest_out else None,
            "total_mins": round(total_mins, 1),
            "total_duration_str": _format_duration(total_mins),
            "total_out_mins": round(total_out_mins, 1),
            "total_out_duration_str": _format_duration(total_out_mins),
            "presence_pct": member_pct,
            "out_pct": out_pct,
            "when_out_str": when_out_str,
            "when_out_short": when_out_short,
            "current_out_mins": round(cur_out_mins, 1),
            "current_out_str": cur_out_str,
            "session_count": len(sessions),
        }
        analyzed_participants.append(p_info)
        team_members[team].append(p_info)

    # 4. Group by team & calculate team-level percentages and Hall Endurance Leaderboard
    team_summaries = []
    venue_counts = defaultdict(int)

    for p in analyzed_participants:
        if p["is_in"] and p["current_venue"]:
            venue_counts[p["current_venue"]] += 1

    for team, members in team_members.items():
        total_m = len(members)
        in_m = sum(1 for m in members if m["is_in"])
        out_m = total_m - in_m
        team_total_mins = sum(m["total_mins"] for m in members)
        avg_mins = (team_total_mins / total_m) if total_m > 0 else 0.0

        occupied_venues = list(sorted({m["current_venue"] for m in members if m["is_in"] and m["current_venue"]}))

        # Team Presence % against event elapsed time
        if effective_elapsed_mins > 0 and total_m > 0:
            expected_team_mins = total_m * effective_elapsed_mins
            team_pct = min(100.0, round((team_total_mins / expected_team_mins * 100.0), 1))
        elif in_m > 0 and total_m > 0:
            team_pct = round((in_m / total_m * 100.0), 1)
        else:
            team_pct = 0.0

        if in_m == total_m and total_m > 0:
            t_status = f"Full Squad IN ({in_m}/{total_m})"
            status_badge = "teal"
        elif in_m > 0:
            t_status = f"Partial IN ({in_m}/{total_m})"
            status_badge = "blue"
        else:
            t_status = f"All OUT (0/{total_m})"
            status_badge = "grey"

        members_out_details = [m for m in members if not m["is_in"]]

        team_summaries.append({
            "team_name": team,
            "total_members": total_m,
            "members_in": in_m,
            "members_out": out_m,
            "presence_pct": team_pct,
            "out_pct": round(max(0.0, 100.0 - team_pct), 1),
            "status": t_status,
            "status_badge": status_badge,
            "venues_occupied": occupied_venues,
            "total_duration_mins": round(team_total_mins, 1),
            "total_duration_str": _format_duration(team_total_mins),
            "avg_duration_str": _format_duration(avg_mins),
            "total_sessions": sum(m["session_count"] for m in members),
            "members": members,
            "members_out_details": members_out_details,
        })

    # Sort teams by Hall Endurance Ranking: most time inside venue first
    team_summaries.sort(key=lambda t: (t["total_duration_mins"], t["presence_pct"], t["members_in"]), reverse=True)
    for idx, t in enumerate(team_summaries, 1):
        t["rank"] = idx

    total_participants = len(analyzed_participants)
    total_currently_in = sum(1 for p in analyzed_participants if p["is_in"])
    total_currently_out = total_participants - total_currently_in

    in_pct = round((total_currently_in / total_participants * 100.0), 1) if total_participants > 0 else 0.0
    out_pct = round((total_currently_out / total_participants * 100.0), 1) if total_participants > 0 else 0.0

    return {
        "team_summaries": team_summaries,
        "participants": analyzed_participants,
        "total_teams": len(team_summaries),
        "total_participants": total_participants,
        "total_currently_in": total_currently_in,
        "total_currently_out": total_currently_out,
        "overall_in_pct": in_pct,
        "overall_out_pct": out_pct,
        "venue_counts": dict(venue_counts),
        "timer": timer,
    }


@router.get("/analytics")
def analytics_page(request: Request):
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect

    from_date = request.query_params.get("from_date") or date.today().isoformat()
    to_date = request.query_params.get("to_date") or date.today().isoformat()
    lab_id_param = request.query_params.get("lab_id")
    lab_id = int(lab_id_param) if lab_id_param else None
    team_name = request.query_params.get("team_name", "").strip()
    status_filter = request.query_params.get("status", "all").strip().lower()
    q = request.query_params.get("q", "").strip()

    conn = get_connection()
    try:
        labs = conn.execute("SELECT * FROM labs ORDER BY id").fetchall()
        teams = [
            r["team_name"] for r in conn.execute(
                "SELECT DISTINCT team_name FROM students WHERE team_name != '' ORDER BY team_name"
            ).fetchall()
        ]
        analytics_data = _calculate_team_analytics(
            conn, from_date, to_date, lab_id, team_name, q, status_filter
        )
    finally:
        conn.close()

    # Spacious 30-Team Bar Chart Data (all 30 teams displayed with zero collapse)
    chart_teams = analytics_data["team_summaries"]
    team_labels = [f"#{t['rank']} {t['team_name']}" for t in chart_teams]
    team_in_vals = [t["presence_pct"] for t in chart_teams]
    team_out_vals = [t["out_pct"] for t in chart_teams]
    team_duration_strs = [t["total_duration_str"] for t in chart_teams]
    team_in_hours = [round(t["total_duration_mins"] / 60.0, 1) for t in chart_teams]

    venue_labels = [l["name"] for l in labs]
    venue_vals = [analytics_data["venue_counts"].get(l["name"], 0) for l in labs]

    context = {
        **admin_template_context(user),
        "active_nav": "analytics",
        "developers": get_developers_context(),
        "labs": labs,
        "teams": teams,
        "selected_lab_id": lab_id,
        "selected_team": team_name,
        "selected_status": status_filter,
        "from_date": from_date,
        "to_date": to_date,
        "q": q,
        "team_labels": team_labels,
        "team_in_vals": team_in_vals,
        "team_out_vals": team_out_vals,
        "team_duration_strs": team_duration_strs,
        "team_in_hours": team_in_hours,
        "venue_labels": venue_labels,
        "venue_vals": venue_vals,
        **analytics_data,
    }
    return templates.TemplateResponse(request, "analytics.html", context)


@router.get("/rankings")
def rankings_page(request: Request):
    """Dedicated Team Rankings View for all 30 teams, accessible from the dedicated sidebar."""
    user, redirect = require_main_admin(request)
    if redirect:
        return redirect

    from_date = request.query_params.get("from_date") or date.today().isoformat()
    to_date = request.query_params.get("to_date") or date.today().isoformat()
    q = request.query_params.get("q", "").strip()

    conn = get_connection()
    try:
        labs = conn.execute("SELECT * FROM labs ORDER BY id").fetchall()
        teams = [
            r["team_name"] for r in conn.execute(
                "SELECT DISTINCT team_name FROM students WHERE team_name != '' ORDER BY team_name"
            ).fetchall()
        ]
        analytics_data = _calculate_team_analytics(
            conn, from_date, to_date, lab_id=None, selected_team="", q=q, status_filter="all"
        )
    finally:
        conn.close()

    context = {
        **admin_template_context(user),
        "active_nav": "rankings",
        "developers": get_developers_context(),
        "labs": labs,
        "teams": teams,
        "from_date": from_date,
        "to_date": to_date,
        "q": q,
        **analytics_data,
    }
    return templates.TemplateResponse(request, "rankings.html", context)


@router.get("/rankings/csv")
def rankings_csv(request: Request):
    """Export the official 30-Team Leaderboard Rankings as CSV."""
    user, redirect = require_main_admin(request)
    if redirect:
        return Response("Unauthorized", status_code=403)

    from_date = request.query_params.get("from_date") or date.today().isoformat()
    to_date = request.query_params.get("to_date") or date.today().isoformat()

    conn = get_connection()
    try:
        analytics_data = _calculate_team_analytics(conn, from_date, to_date)
    finally:
        conn.close()

    lines = ["Rank,Team Name,Presence (%),Total Time in Hall,Members IN,Total Members,Squad Status,Active Venues"]
    for t in analytics_data["team_summaries"]:
        venues_str = "; ".join(t["venues_occupied"]) if t["venues_occupied"] else "All OUT"
        lines.append(
            f"{t['rank']},\"{t['team_name']}\",{t['presence_pct']}%,{t['total_duration_str']},"
            f"{t['members_in']},{t['total_members']},\"{t['status']}\",\"{venues_str}\""
        )

    csv_data = "\r\n".join(lines)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=hackathon_team_rankings_{from_date}.csv"},
    )


@router.get("/analytics/scans/csv")
def scan_audit_csv(request: Request):
    """Export all raw scan events and duplicate detections as CSV audit trail."""
    user, redirect = require_main_admin(request)
    if redirect:
        return Response("Unauthorized", status_code=403)

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT sl.id, sl.roll_no, s.name, COALESCE(s.team_name, 'No Team') AS team_name, "
            "l.name AS lab_name, sl.scan_time, sl.action, sl.confidence "
            "FROM scan_logs sl "
            "JOIN students s ON s.roll_no = sl.roll_no "
            "JOIN labs l ON l.id = sl.lab_id "
            "ORDER BY sl.id DESC LIMIT 5000"
        ).fetchall()
    finally:
        conn.close()

    lines = ["Scan ID,Participant ID,Full Name,Team Name,Venue,Scan Timestamp,Action Detected,Confidence"]
    for r in rows:
        lines.append(
            f"{r['id']},\"{r['roll_no']}\",\"{r['name']}\",\"{r['team_name']}\",\"{r['lab_name']}\","
            f"\"{r['scan_time']}\",\"{r['action']}\",{r['confidence'] or 0.0}"
        )

    csv_data = "\r\n".join(lines)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=hackathon_scan_audit_log.csv"},
    )


@router.post("/api/event-timer/start")
def event_timer_start(request: Request):
    user, redirect = require_main_admin(request)
    if redirect:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=403)

    conn = get_connection()
    try:
        existing = conn.execute("SELECT value FROM event_config WHERE key='start_time'").fetchone()
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not existing or not existing["value"]:
            conn.execute("INSERT OR REPLACE INTO event_config (key, value) VALUES ('start_time', ?)", (now_iso,))
        conn.execute("INSERT OR REPLACE INTO event_config (key, value) VALUES ('is_active', '1')")
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse("/analytics?success=Master Event Timer Started", status_code=302)


@router.post("/api/event-timer/pause")
def event_timer_pause(request: Request):
    user, redirect = require_main_admin(request)
    if redirect:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=403)

    conn = get_connection()
    try:
        conn.execute("INSERT OR REPLACE INTO event_config (key, value) VALUES ('is_active', '0')")
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse("/analytics?success=Master Event Timer Paused", status_code=302)


@router.post("/api/event-timer/reset")
def event_timer_reset(request: Request):
    user, redirect = require_main_admin(request)
    if redirect:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=403)

    conn = get_connection()
    try:
        conn.execute("INSERT OR REPLACE INTO event_config (key, value) VALUES ('is_active', '0')")
        conn.execute("INSERT OR REPLACE INTO event_config (key, value) VALUES ('start_time', '')")
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse("/analytics?success=Master Event Timer Reset to 24:00:00", status_code=302)
