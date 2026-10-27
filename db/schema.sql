PRAGMA foreign_keys = ON;

-- Venues / Labs (Editable across the 3 event venues)
CREATE TABLE IF NOT EXISTS labs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL UNIQUE,
    clear_lab_password TEXT NOT NULL DEFAULT 'clear123'
);

-- User authentication (Admins and Venue Operators)
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'user')),
    lab_id        INTEGER REFERENCES labs(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Hackathon Participants (Roll No / ID, Name, Team Name)
CREATE TABLE IF NOT EXISTS students (
    roll_no     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    team_name   TEXT NOT NULL,
    photo_path  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_students_team_name ON students(team_name);

-- Face Recognition Embeddings (Insightface 512-d cosine vectors)
CREATE TABLE IF NOT EXISTS embeddings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    roll_no     TEXT NOT NULL REFERENCES students(roll_no) ON DELETE CASCADE,
    embedding   BLOB NOT NULL,
    angle_label TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_embeddings_roll_no ON embeddings(roll_no);

-- Live Attendance Sessions (IN / OUT across the 3 venues)
CREATE TABLE IF NOT EXISTS attendance (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    roll_no       TEXT NOT NULL REFERENCES students(roll_no) ON DELETE CASCADE,
    lab_id        INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    session_date  TEXT NOT NULL,
    in_time       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    out_time      TEXT,
    out_date      TEXT
);

CREATE INDEX IF NOT EXISTS idx_attendance_dedup ON attendance(roll_no, session_date, lab_id);
CREATE INDEX IF NOT EXISTS idx_attendance_session_date ON attendance(session_date);
CREATE INDEX IF NOT EXISTS idx_attendance_in_time ON attendance(in_time);

-- Master Event Configuration & Timer
CREATE TABLE IF NOT EXISTS event_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Raw Scan Audit Logs (Records each and every scan/detection event including duplicate/repeated scans)
CREATE TABLE IF NOT EXISTS scan_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    roll_no      TEXT NOT NULL REFERENCES students(roll_no) ON DELETE CASCADE,
    lab_id       INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    scan_time    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    action       TEXT NOT NULL, -- 'IN', 'OUT', 'DUPLICATE_IN', 'DUPLICATE_OUT', 'DETECTED'
    confidence   REAL,
    created_date TEXT NOT NULL DEFAULT (date('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_scan_logs_roll_no ON scan_logs(roll_no);
CREATE INDEX IF NOT EXISTS idx_scan_logs_lab_id ON scan_logs(lab_id);
CREATE INDEX IF NOT EXISTS idx_scan_logs_time ON scan_logs(scan_time);
