import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .permissions import ROLE_LABELS, Perm, Role, role_can

STATUSES = ("success", "warning", "failed", "pending")
STATUS_LABELS = {"success": "Сәтті", "warning": "Ескерту", "failed": "Сәтсіз", "pending": "Күтілуде"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value):
    if not value:
        return None
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class User:
    id: int
    full_name: str
    username: str
    email: str
    phone: str
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None

    @property
    def role_label(self):
        return ROLE_LABELS[self.role]

    @property
    def initials(self):
        parts = [part for part in self.full_name.split() if part]
        return ("".join(part[0] for part in parts[:2]) or self.username[:1]).upper()

    def can(self, perm: Perm) -> bool:
        return role_can(self.role, perm)

    @property
    def first_name(self):
        return self.full_name.split()[0] if self.full_name.split() else self.username


@dataclass(frozen=True)
class Equipment:
    id: int
    code: str
    name: str
    model: str
    category: str
    kind: str
    profile: str
    created_by: int | None

    @property
    def label(self):
        return f"{self.name} · {self.model}" if self.model else self.name


@dataclass(frozen=True)
class HistoryRecord:
    id: int
    test_code: str
    user_id: int | None
    operator: str
    equipment_id: int
    equipment_code: str
    equipment_name: str
    equipment_model: str
    category: str
    performed_at: datetime
    parameters: dict = field(default_factory=dict)
    result: str = ""
    details: dict = field(default_factory=dict)
    status: str = "pending"
    notes: str = ""
    is_demo: bool = False

    @property
    def status_label(self):
        return STATUS_LABELS[self.status]


@dataclass(frozen=True)
class Session:
    user: User
    token: str
    expires_at: datetime
    remember: bool


def dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def loads(text, default):
    try:
        value = json.loads(text) if text else default
    except ValueError:
        return default
    return value if isinstance(value, type(default)) else default
