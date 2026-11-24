"""SQLite connection, schema and first-run seed data."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import CATEGORIES, database_path
from .diagnostics import PROFILES, evaluate
from .models import dumps

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name        TEXT NOT NULL,
    username         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email            TEXT NOT NULL UNIQUE COLLATE NOCASE,
    phone            TEXT NOT NULL DEFAULT '',
    password_hash    TEXT NOT NULL,
    role             TEXT NOT NULL CHECK (role IN ('administrator','mechanic','engineer','guest')),
    is_active        INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    failed_attempts  INTEGER NOT NULL DEFAULT 0,
    locked_until     TEXT,
    reset_code_hash  TEXT,
    reset_expires_at TEXT,
    reset_attempts   INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    last_login_at    TEXT
);

CREATE TABLE IF NOT EXISTS equipment (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name       TEXT NOT NULL,
    model      TEXT NOT NULL DEFAULT '',
    category   TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT '',
    profile    TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS diagnostic_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    test_code     TEXT NOT NULL UNIQUE,
    user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    operator_name TEXT NOT NULL DEFAULT '',
    equipment_id  INTEGER NOT NULL REFERENCES equipment(id) ON DELETE RESTRICT,
    performed_at  TEXT NOT NULL,
    parameters    TEXT NOT NULL DEFAULT '{}',
    result        TEXT NOT NULL DEFAULT '',
    details       TEXT NOT NULL DEFAULT '{}',
    status        TEXT NOT NULL CHECK (status IN ('success','warning','failed','pending')),
    notes         TEXT NOT NULL DEFAULT '',
    is_demo       INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0,1))
);
CREATE INDEX IF NOT EXISTS idx_history_user      ON diagnostic_history(user_id, performed_at);
CREATE INDEX IF NOT EXISTS idx_history_equipment ON diagnostic_history(equipment_id, performed_at);
CREATE INDEX IF NOT EXISTS idx_history_status    ON diagnostic_history(status);

CREATE TABLE IF NOT EXISTS user_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash   TEXT NOT NULL UNIQUE,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    remember     INTEGER NOT NULL DEFAULT 0,
    revoked_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id);

CREATE TABLE IF NOT EXISTS system_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# (code, name, model, category, kind, profile)
SEED_EQUIPMENT = (
    ("M-4000", "M-4000", "Electric Motor", CATEGORIES[0], "Электр қозғалтқышы", "motor"),
    ("AUTO-2800", "Автокөлік қозғалтқышы", "Бензинді қозғалтқыш", CATEGORIES[4], "Бензинді қозғалтқыш", "automotive"),
    ("TF-3800", "Ұшақ қозғалтқышы", "Турбожелдеткіш қозғалтқыш", CATEGORIES[2], "Турбожелдеткіш қозғалтқыш", "turbofan"),
    ("BOSCH-GBH-2-28F", "Bosch GBH 2-28 F", "Hammer Drill", CATEGORIES[1], "Электр құралы", "power_tool"),
    ("BOSCH-GBH", "Bosch GBH", "Hammer Drill", CATEGORIES[1], "Электр құралы", "power_tool"),
)

# The three sample diagnostics the original SmartDiagnost demo shipped with.
# (id, test code, equipment code, performed_at (UTC), result text, measured values)
SEED_HISTORY = (
    (246, "SD-0246", "BOSCH-GBH", "2024-06-26T09:15:00+00:00", "Қалыпты",
     {"temperature": 37, "vibration": 0.9, "current": 3.3}),
    (247, "SD-0247", "M-4000", "2024-06-27T08:40:00+00:00", "Мойынтірек тозуы",
     {"temperature": 83, "vibration": 2.7, "speed": 1496, "torque": 12.9, "field": 0.42}),
    (248, "SD-0248", "BOSCH-GBH-2-28F", "2024-06-27T11:05:00+00:00", "Қалыпты",
     {"temperature": 38, "vibration": 1.0, "current": 3.4}),
)


class Database:
    def __init__(self, path=None):
        target = ":memory:" if path == ":memory:" else str(Path(path) if path else database_path())
        self.conn = sqlite3.connect(target)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.init()

    def init(self):
        with self.conn:
            self.conn.executescript(SCHEMA)
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._seed()

    @contextmanager
    def transaction(self):
        """Commit on success, roll back on any exception."""
        with self.conn:
            yield self.conn

    def close(self):
        self.conn.close()

    def _seed(self):
        if self.conn.execute("SELECT COUNT(*) FROM equipment").fetchone()[0]:
            return
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.conn:
            ids = {}
            for code, name, model, category, kind, profile in SEED_EQUIPMENT:
                cursor = self.conn.execute(
                    "INSERT INTO equipment (code, name, model, category, kind, profile, created_by, created_at)"
                    " VALUES (?,?,?,?,?,?,NULL,?)",
                    (code, name, model, category, kind, profile, now),
                )
                ids[code] = cursor.lastrowid
            profiles = {code: profile for code, *_rest, profile in SEED_EQUIPMENT}
            for record_id, test_code, code, performed_at, result, values in SEED_HISTORY:
                profile = PROFILES[profiles[code]]
                outcome = evaluate(profile, values)
                details = dict(outcome.as_dict(), profile=profile.key, advanced=False, margin=0.1)
                self.conn.execute(
                    "INSERT INTO diagnostic_history (id, test_code, user_id, operator_name, equipment_id, performed_at,"
                    " parameters, result, details, status, notes, is_demo) VALUES (?,?,NULL,?,?,?,?,?,?,?,?,1)",
                    (record_id, test_code, "SmartDiagnost Demo", ids[code], performed_at, dumps(values), result,
                     dumps(details), outcome.status, "Үлгі диагностика (демо деректер)."),
                )
