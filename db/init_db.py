"""Initialize and manage the SQLite database for the 24-Hour Hackathon Face Recognition platform."""

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import DATA_DIR, DB_PATH, ENROLLMENT_PHOTOS_DIR
from core.security import hash_password
from db.connection import get_connection

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def reset_hackathon_db() -> None:
    """Completely wipe academic / demo data and initialize a clean 24-hour hackathon database.
    Leaves 0 participants so real hackathon teams can be registered cleanly."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ENROLLMENT_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    # Clean old enrollment photos
    for item in ENROLLMENT_PHOTOS_DIR.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        elif item.is_file():
            item.unlink()

    conn = get_connection()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        
        # Drop legacy tables, labs, and users
        legacy_tables = [
            "faculty_attendance", "faculty_embeddings", "faculty", "faculty_roles",
            "periods", "periods_new", "shutdown_times", "class_strength",
            "attendance", "embeddings", "students", "event_config", "labs",
            "batch_runs", "batch_run_students", "batch_run_embeddings", "users"
        ]
        for tbl in legacy_tables:
            conn.execute(f"DROP TABLE IF EXISTS {tbl}")
        
        # Re-run clean schema
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema_sql)

        # Seed default admin user (admin / admin123)
        admin_exists = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
        if not admin_exists:
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                ("admin", hash_password("admin123"), "admin")
            )

        # Seed the 3 editable venues if not present
        existing_labs = conn.execute("SELECT COUNT(*) c FROM labs").fetchone()["c"]
        if existing_labs == 0:
            venues = [
                ("Venue 1 - Main Coding Hall", "venue1"),
                ("Venue 2 - Mentorship Hall", "venue2"),
                ("Venue 3 - Presentation Hall", "venue3"),
            ]
            for v_name, u_name in venues:
                cur = conn.execute("INSERT INTO labs (name) VALUES (?)", (v_name,))
                lab_id = cur.lastrowid
                conn.execute(
                    "INSERT INTO users (username, password_hash, role, lab_id) VALUES (?, ?, ?, ?)",
                    (u_name, hash_password("venue123"), "user", lab_id)
                )

        # Seed master event config
        defaults = {
            "event_name": "PSNA IT 24-Hour Hackathon",
            "duration_hours": "24",
            "is_active": "0",
            "start_time": "",
            "max_team_size": "4",
            "max_teams": "30",
        }
        for k, v in defaults.items():
            conn.execute("INSERT OR REPLACE INTO event_config (key, value) VALUES (?, ?)", (k, v))

        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
    finally:
        conn.close()

    print(f"Hackathon database cleanly reset at {DB_PATH} with 0 participants and 3 editable venues.")


def init_db() -> None:
    """Ensure database schema is up-to-date without wiping existing data."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ENROLLMENT_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema_sql)

        # Ensure admin exists
        admin_exists = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
        if not admin_exists:
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                ("admin", hash_password("admin123"), "admin")
            )

        # Ensure event_config defaults exist
        defaults = {
            "event_name": "PSNA IT 24-Hour Hackathon",
            "duration_hours": "24",
            "is_active": "0",
            "start_time": "",
            "max_team_size": "4",
            "max_teams": "30",
        }
        for k, v in defaults.items():
            conn.execute("INSERT OR IGNORE INTO event_config (key, value) VALUES (?, ?)", (k, v))

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    # If called with --reset or standalone, do clean reset
    if "--init-only" in sys.argv:
        init_db()
    else:
        reset_hackathon_db()
