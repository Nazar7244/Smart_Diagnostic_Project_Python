"""Remember-me: keeps the raw session token of this device in the user's profile folder.

The server side (user_sessions) only stores a SHA-256 hash of the token, expires it,
and revokes it on logout, a password change or when the account is disabled.
"""
import json
import os
from pathlib import Path

from .config import data_dir


class RememberStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / "remember.json"

    def load(self) -> str:
        try:
            token = json.loads(self.path.read_text(encoding="utf-8")).get("token", "")
        except (OSError, ValueError, AttributeError):
            return ""
        return token if isinstance(token, str) else ""

    def save(self, token: str):
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps({"token": token}), encoding="utf-8")
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self.path)
        except OSError:
            pass  # remember-me is a convenience; failing to persist must never block login

    def clear(self):
        try:
            self.path.unlink()
        except OSError:
            pass
