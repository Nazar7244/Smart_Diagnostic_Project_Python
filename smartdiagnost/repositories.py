"""Data access: plain parameterised SQL, no permission logic (that lives in services/auth)."""
from datetime import datetime

from .models import Equipment, HistoryRecord, User, iso, loads, parse_iso
from .permissions import Role

DEFAULT_SETTINGS = {
    "registration_open": "1",
    "session_hours": "8",
    "remember_days": "30",
    "max_failed_attempts": "5",
    "lockout_minutes": "5",
}


def like_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def row_to_user(row) -> User:
    return User(
        id=row["id"], full_name=row["full_name"], username=row["username"], email=row["email"],
        phone=row["phone"], role=Role(row["role"]), is_active=bool(row["is_active"]),
        created_at=parse_iso(row["created_at"]), last_login_at=parse_iso(row["last_login_at"]),
    )


def row_to_equipment(row) -> Equipment:
    return Equipment(
        id=row["id"], code=row["code"], name=row["name"], model=row["model"], category=row["category"],
        kind=row["kind"], profile=row["profile"], created_by=row["created_by"],
    )


def row_to_record(row) -> HistoryRecord:
    return HistoryRecord(
        id=row["id"], test_code=row["test_code"], user_id=row["user_id"], operator=row["operator"] or "—",
        equipment_id=row["equipment_id"], equipment_code=row["eq_code"], equipment_name=row["eq_name"],
        equipment_model=row["eq_model"], category=row["eq_category"], performed_at=parse_iso(row["performed_at"]),
        parameters=loads(row["parameters"], {}), result=row["result"], details=loads(row["details"], {}),
        status=row["status"], notes=row["notes"], is_demo=bool(row["is_demo"]),
    )


class SettingsRepository:
    def __init__(self, db):
        self.db = db

    def get(self, key: str) -> str:
        row = self.db.conn.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else DEFAULT_SETTINGS[key]

    def all(self) -> dict:
        values = dict(DEFAULT_SETTINGS)
        values.update({r["key"]: r["value"] for r in self.db.conn.execute("SELECT key, value FROM system_settings")})
        return values

    def set(self, key: str, value: str):
        if key not in DEFAULT_SETTINGS:
            raise KeyError(key)
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO system_settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)),
            )


class UserRepository:
    def __init__(self, db):
        self.db = db

    @property
    def conn(self):
        return self.db.conn

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def count_admins(self, active_only=False) -> int:
        sql = "SELECT COUNT(*) FROM users WHERE role = 'administrator'" + (" AND is_active = 1" if active_only else "")
        return self.conn.execute(sql).fetchone()[0]

    def get_row(self, user_id: int):
        return self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def get(self, user_id: int):
        row = self.get_row(user_id)
        return row_to_user(row) if row else None

    def find_row(self, identifier: str):
        return self.conn.execute(
            "SELECT * FROM users WHERE username = ? OR email = ?", (identifier.strip(), identifier.strip())
        ).fetchone()

    def conflicts(self, username: str, email: str, exclude_id: int | None = None) -> list:
        found = []
        rows = self.conn.execute(
            "SELECT username, email FROM users WHERE (username = ? OR email = ?) AND id != ?",
            (username.strip(), email.strip(), exclude_id or -1),
        ).fetchall()
        for row in rows:
            if row["username"].casefold() == username.strip().casefold():
                found.append("Бұл пайдаланушы аты бос емес.")
            if row["email"].casefold() == email.strip().casefold():
                found.append("Бұл email бұрын тіркелген.")
        return list(dict.fromkeys(found))

    def insert(self, *, full_name, username, email, phone, password_hash, role: Role, created_at: datetime) -> int:
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO users (full_name, username, email, phone, password_hash, role, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (full_name.strip(), username.strip(), email.strip(), phone.strip(), password_hash, role.value, iso(created_at)),
            )
        return cursor.lastrowid

    def update(self, user_id: int, **fields):
        allowed = {"full_name", "username", "email", "phone", "role", "is_active"}
        if not fields or set(fields) - allowed:
            raise ValueError("unsupported fields")
        values = [v.value if isinstance(v, Role) else int(v) if isinstance(v, bool) else v for v in fields.values()]
        with self.db.transaction() as conn:
            conn.execute(f"UPDATE users SET {', '.join(f'{name} = ?' for name in fields)} WHERE id = ?", (*values, user_id))

    def set_password(self, user_id: int, password_hash: str):
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, failed_attempts = 0, locked_until = NULL,"
                " reset_code_hash = NULL, reset_expires_at = NULL, reset_attempts = 0 WHERE id = ?",
                (password_hash, user_id),
            )

    def record_failure(self, user_id: int, attempts: int, locked_until: datetime | None):
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                (attempts, iso(locked_until) if locked_until else None, user_id),
            )

    def record_success(self, user_id: int, when: datetime):
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = ? WHERE id = ?",
                (iso(when), user_id),
            )

    def set_reset(self, user_id: int, code_hash: str, expires: datetime):
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE users SET reset_code_hash = ?, reset_expires_at = ?, reset_attempts = 0 WHERE id = ?",
                (code_hash, iso(expires), user_id),
            )

    def bump_reset_attempts(self, user_id: int):
        with self.db.transaction() as conn:
            conn.execute("UPDATE users SET reset_attempts = reset_attempts + 1 WHERE id = ?", (user_id,))

    def list(self, search: str = "", role: Role | None = None) -> list:
        sql, params = "SELECT * FROM users WHERE 1=1", []
        if search.strip():
            sql += " AND (full_name LIKE ? ESCAPE '\\' OR username LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\')"
            params += [like_pattern(search.strip())] * 3
        if role:
            sql += " AND role = ?"
            params.append(role.value)
        return [row_to_user(r) for r in self.conn.execute(sql + " ORDER BY full_name COLLATE NOCASE", params)]

    def delete(self, user_id: int):
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def counts_by_role(self) -> dict:
        rows = self.conn.execute("SELECT role, COUNT(*) AS n FROM users GROUP BY role").fetchall()
        return {Role(r["role"]): r["n"] for r in rows}

    def count_active(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0]


class SessionRepository:
    def __init__(self, db):
        self.db = db

    def create(self, user_id, token_hash, created: datetime, expires: datetime, remember: bool):
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO user_sessions (user_id, token_hash, created_at, expires_at, last_seen_at, remember)"
                " VALUES (?,?,?,?,?,?)",
                (user_id, token_hash, iso(created), iso(expires), iso(created), int(remember)),
            )

    def find_valid(self, token_hash: str, now: datetime):
        """Return (user row, session row) for a live session, or None."""
        row = self.db.conn.execute(
            "SELECT s.expires_at, s.remember, u.* FROM user_sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ?",
            (token_hash, iso(now)),
        ).fetchone()
        return row

    def touch(self, token_hash: str, now: datetime):
        with self.db.transaction() as conn:
            conn.execute("UPDATE user_sessions SET last_seen_at = ? WHERE token_hash = ?", (iso(now), token_hash))

    def revoke(self, token_hash: str, now: datetime):
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE user_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (iso(now), token_hash),
            )

    def revoke_user(self, user_id: int, now: datetime, except_hash: str | None = None):
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE user_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL AND token_hash != ?",
                (iso(now), user_id, except_hash or ""),
            )

    def purge(self, now: datetime):
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM user_sessions WHERE expires_at <= ? OR revoked_at IS NOT NULL", (iso(now),))

    def count_active(self, user_id: int, now: datetime) -> int:
        return self.db.conn.execute(
            "SELECT COUNT(*) FROM user_sessions WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ?",
            (user_id, iso(now)),
        ).fetchone()[0]


class EquipmentRepository:
    def __init__(self, db):
        self.db = db

    def list(self) -> list:
        rows = self.db.conn.execute("SELECT * FROM equipment ORDER BY name COLLATE NOCASE, id")
        return [row_to_equipment(r) for r in rows]

    def get(self, equipment_id: int):
        row = self.db.conn.execute("SELECT * FROM equipment WHERE id = ?", (equipment_id,)).fetchone()
        return row_to_equipment(row) if row else None

    def code_exists(self, code: str) -> bool:
        return self.db.conn.execute("SELECT 1 FROM equipment WHERE code = ?", (code,)).fetchone() is not None

    def insert(self, *, code, name, model, category, kind, profile, created_by, created_at: datetime, conn=None) -> int:
        sql = (
            "INSERT INTO equipment (code, name, model, category, kind, profile, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)"
        )
        args = (code, name, model, category, kind, profile, created_by, iso(created_at))
        if conn is not None:
            return conn.execute(sql, args).lastrowid
        with self.db.transaction() as txn:
            return txn.execute(sql, args).lastrowid

    def rename(self, equipment_id: int, name: str, model: str, conn=None):
        sql, args = "UPDATE equipment SET name = ?, model = ? WHERE id = ?", (name, model, equipment_id)
        if conn is not None:
            conn.execute(sql, args)
            return
        with self.db.transaction() as txn:
            txn.execute(sql, args)


OPERATOR_EXPR = "COALESCE(u.full_name, NULLIF(h.operator_name, ''))"
HISTORY_SELECT = (
    "SELECT h.*, e.code AS eq_code, e.name AS eq_name, e.model AS eq_model, e.category AS eq_category,"
    f" {OPERATOR_EXPR} AS operator"
    " FROM diagnostic_history h JOIN equipment e ON e.id = h.equipment_id LEFT JOIN users u ON u.id = h.user_id"
)


class HistoryRepository:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def _scope(scope: str, user_id: int | None):
        if scope == "all":
            return "1=1", []
        if scope == "own":
            return "h.user_id = ? AND h.is_demo = 0", [user_id]
        return "h.is_demo = 1", []

    def search(self, scope, user_id, *, text="", status=None, operator_id=None, since: datetime | None = None,
               until: datetime | None = None, limit: int | None = None) -> list:
        where, params = self._scope(scope, user_id)
        if text.strip():
            pattern = like_pattern(text.strip())
            fields = ("h.test_code", "e.name", "e.model", "e.code", OPERATOR_EXPR, "h.result")
            where += " AND (" + " OR ".join(f"{f} LIKE ? ESCAPE '\\'" for f in fields) + ")"
            params += [pattern] * len(fields)
        if status:
            where += " AND h.status = ?"
            params.append(status)
        if operator_id:
            where += " AND h.user_id = ?"
            params.append(operator_id)
        if since:
            where += " AND h.performed_at >= ?"
            params.append(iso(since))
        if until:
            where += " AND h.performed_at < ?"
            params.append(iso(until))
        sql = f"{HISTORY_SELECT} WHERE {where} ORDER BY h.performed_at DESC, h.id DESC" + (" LIMIT ?" if limit else "")
        if limit:
            params.append(limit)
        return [row_to_record(r) for r in self.db.conn.execute(sql, params)]

    def get(self, record_id: int):
        row = self.db.conn.execute(f"{HISTORY_SELECT} WHERE h.id = ?", (record_id,)).fetchone()
        return row_to_record(row) if row else None

    def counts(self, scope, user_id) -> dict:
        where, params = self._scope(scope, user_id)
        rows = self.db.conn.execute(
            f"SELECT h.status, COUNT(*) AS n FROM diagnostic_history h WHERE {where} GROUP BY h.status", params
        ).fetchall()
        counts = {"success": 0, "warning": 0, "failed": 0, "pending": 0}
        counts.update({r["status"]: r["n"] for r in rows})
        return counts

    def insert(self, conn, *, user_id, operator_name, equipment_id, performed_at: datetime, parameters, result,
               details, status, notes="") -> int:
        cursor = conn.execute(
            "INSERT INTO diagnostic_history (test_code, user_id, operator_name, equipment_id, performed_at,"
            " parameters, result, details, status, notes, is_demo)"
            " VALUES ('TMP-' || hex(randomblob(6)),?,?,?,?,?,?,?,?,?,0)",
            (user_id, operator_name, equipment_id, iso(performed_at), parameters, result, details, status, notes),
        )
        record_id = cursor.lastrowid
        conn.execute("UPDATE diagnostic_history SET test_code = printf('SD-%04d', id) WHERE id = ?", (record_id,))
        return record_id

    def update_notes(self, record_id: int, notes: str, conn=None):
        sql, args = "UPDATE diagnostic_history SET notes = ? WHERE id = ?", (notes, record_id)
        if conn is not None:
            conn.execute(sql, args)
            return
        with self.db.transaction() as txn:
            txn.execute(sql, args)

    def delete(self, record_id: int):
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM diagnostic_history WHERE id = ?", (record_id,))

    def for_equipment(self, equipment_id: int, scope, user_id, limit=30) -> list:
        where, params = self._scope(scope, user_id)
        rows = self.db.conn.execute(
            f"{HISTORY_SELECT} WHERE {where} AND h.equipment_id = ? AND h.status != 'pending'"
            " ORDER BY h.performed_at DESC, h.id DESC LIMIT ?",
            (*params, equipment_id, limit),
        )
        return [row_to_record(r) for r in rows]

    def total(self) -> int:
        return self.db.conn.execute("SELECT COUNT(*) FROM diagnostic_history").fetchone()[0]

    def since_count(self, since: datetime) -> int:
        return self.db.conn.execute(
            "SELECT COUNT(*) FROM diagnostic_history WHERE performed_at >= ? AND is_demo = 0", (iso(since),)
        ).fetchone()[0]

    def top_operators(self, limit=5) -> list:
        rows = self.db.conn.execute(
            "SELECT COALESCE(u.full_name, h.operator_name) AS name, COUNT(*) AS n FROM diagnostic_history h"
            " LEFT JOIN users u ON u.id = h.user_id WHERE h.is_demo = 0 GROUP BY h.user_id, name"
            " ORDER BY n DESC LIMIT ?", (limit,),
        ).fetchall()
        return [(r["name"] or "—", r["n"]) for r in rows]
