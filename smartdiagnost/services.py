"""Business rules with role checks. Every method that touches protected data takes the acting user."""
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from . import diagnostics, security
from .auth import AuthService, require, validate_profile_fields
from .config import CATEGORIES
from .database import Database
from .errors import NotFound, PermissionDenied, ValidationError
from .models import HistoryRecord, User, dumps, utc_now
from .permissions import Perm, Role
from .repositories import (
    DEFAULT_SETTINGS, EquipmentRepository, HistoryRepository, SessionRepository, SettingsRepository, UserRepository,
)

SETTING_LIMITS = {
    "session_hours": (1, 72),
    "remember_days": (1, 90),
    "max_failed_attempts": (3, 10),
    "lockout_minutes": (1, 60),
}


def local_day_start(day: date) -> datetime:
    """Midnight at the start of a local calendar day, as an aware datetime."""
    return datetime.combine(day, time.min).astimezone()


# ---------------------------------------------------------------- users

class UserService:
    def __init__(self, users: UserRepository, sessions: SessionRepository, auth: AuthService):
        self.users, self.sessions, self.auth = users, sessions, auth

    def list(self, actor: User, search="", role: Role | None = None) -> list:
        require(actor, Perm.USERS_MANAGE)
        return self.users.list(search, role)

    def create(self, actor: User, *, full_name, username, email, phone, password, role) -> User:
        return self.auth.register(
            full_name=full_name, username=username, email=email, phone=phone, password=password,
            confirm_password=password, role=role, actor=actor,
        )

    def _would_orphan_admins(self, target: User, new_role: Role, active: bool) -> bool:
        if target.role is not Role.ADMIN or not target.is_active:
            return False
        return (new_role is not Role.ADMIN or not active) and self.users.count_admins(active_only=True) <= 1

    def update(self, actor: User, user_id: int, *, full_name, email, phone, role, is_active, new_password=None) -> User:
        require(actor, Perm.USERS_MANAGE)
        target = self.users.get(user_id)
        if target is None:
            raise NotFound("Пайдаланушы табылмады.")
        role = Role(role)
        errors = validate_profile_fields(full_name, target.username, email, phone)
        errors += self.users.conflicts(target.username, email, exclude_id=user_id)
        if new_password:
            errors += security.validate_password(new_password, target.username, email, full_name)
        if target.id == actor.id and not is_active:
            errors.append("Өз тіркелгіңізді өшіре алмайсыз.")
        if self._would_orphan_admins(target, role, is_active):
            errors.append("Жүйеде кемінде бір белсенді әкімші болуы керек.")
        if errors:
            raise ValidationError(errors)
        self.users.update(user_id, full_name=full_name.strip(), email=email.strip(), phone=phone.strip(),
                          role=role, is_active=is_active)
        if new_password:
            self.users.set_password(user_id, security.hash_password(new_password))
        if new_password or not is_active:
            self.sessions.revoke_user(user_id, utc_now())
        return self.users.get(user_id)

    def delete(self, actor: User, user_id: int):
        require(actor, Perm.USERS_MANAGE)
        target = self.users.get(user_id)
        if target is None:
            raise NotFound("Пайдаланушы табылмады.")
        if target.id == actor.id:
            raise ValidationError("Өз тіркелгіңізді жоюға болмайды.")
        if self._would_orphan_admins(target, Role.GUEST, False):
            raise ValidationError("Соңғы белсенді әкімшіні жоюға болмайды.")
        self.users.delete(user_id)  # sessions cascade; reports are kept with the operator name

    def issue_reset_code(self, actor: User, user_id: int) -> str:
        return self.auth.issue_reset_code(actor, user_id)


# ---------------------------------------------------------------- equipment & history

def can_rename_equipment(actor: User, equipment) -> bool:
    """Admins may rename any equipment; others only equipment they registered themselves."""
    return actor.can(Perm.HISTORY_ALL) or (
        actor.can(Perm.HISTORY_EDIT) and equipment.created_by is not None and equipment.created_by == actor.id
    )


class EquipmentService:
    def __init__(self, repo: EquipmentRepository):
        self.repo = repo

    def list(self):
        return self.repo.list()

    def get(self, equipment_id: int):
        equipment = self.repo.get(equipment_id)
        if equipment is None:
            raise NotFound("Жабдық табылмады.")
        return equipment

    can_rename = staticmethod(can_rename_equipment)


class HistoryService:
    def __init__(self, repo: HistoryRepository, equipment: EquipmentRepository, db: Database):
        self.repo, self.equipment, self.db = repo, equipment, db

    # -- scope -------------------------------------------------------------
    @staticmethod
    def scope(actor: User) -> str:
        if actor.can(Perm.HISTORY_ALL):
            return "all"
        if actor.can(Perm.HISTORY_OWN):
            return "own"
        if actor.can(Perm.HISTORY_DEMO):
            return "demo"
        raise PermissionDenied()

    def _visible(self, actor: User, record: HistoryRecord) -> bool:
        scope = self.scope(actor)
        return scope == "all" or (scope == "own" and record.user_id == actor.id and not record.is_demo) or (
            scope == "demo" and record.is_demo
        )

    def _editable(self, actor: User, record: HistoryRecord) -> bool:
        if not actor.can(Perm.HISTORY_EDIT):
            return False
        return actor.can(Perm.HISTORY_ALL) or (record.user_id == actor.id and not record.is_demo)

    def can_modify(self, actor: User, record: HistoryRecord) -> bool:
        return self._editable(actor, record)

    # -- reading -----------------------------------------------------------
    def search(self, actor: User, *, text="", status=None, operator_id=None, date_from: date | None = None,
               date_to: date | None = None, limit=None) -> list:
        since = local_day_start(date_from) if date_from else None
        until = local_day_start(date_to + timedelta(days=1)) if date_to else None
        if operator_id and self.scope(actor) != "all":
            operator_id = actor.id
        return self.repo.search(self.scope(actor), actor.id, text=text, status=status, operator_id=operator_id,
                                since=since, until=until, limit=limit)

    def get(self, actor: User, record_id: int) -> HistoryRecord:
        record = self.repo.get(record_id)
        if record is None or not self._visible(actor, record):
            raise NotFound()
        return record

    def counts(self, actor: User) -> dict:
        counts = self.repo.counts(self.scope(actor), actor.id)
        counts["total"] = sum(counts.values())
        return counts

    def trend(self, actor: User, equipment_id: int, limit=30) -> list:
        """Saved results of one equipment, oldest first (needs the measurements permission)."""
        require(actor, Perm.MEASUREMENTS_VIEW)
        return list(reversed(self.repo.for_equipment(equipment_id, self.scope(actor), actor.id, limit)))

    # -- writing -----------------------------------------------------------
    def register_check(self, actor: User, *, device, model, category, code="") -> HistoryRecord:
        """The original "new check" form: register a device and open a pending diagnostic for it."""
        require(actor, Perm.DIAG_EQUIPMENT)
        require(actor, Perm.DIAG_RUN)
        device, model, code = device.strip(), model.strip(), code.strip()
        errors = []
        if not device or not model:
            errors.append("Құрылғы атауы мен моделін енгізіңіз.")
        if len(device) > 80 or len(model) > 80:
            errors.append("Атау мен модель 80 таңбадан аспауы керек.")
        if category not in CATEGORIES:
            errors.append("Санатты таңдаңыз.")
        if code and not re.fullmatch(r"[\w.\- ]{1,40}", code):
            errors.append("Құрылғы ID: әріп, сан, - _ . ғана (40 таңбаға дейін).")
        elif code and self.equipment.code_exists(code):
            errors.append("Бұл ID бұрыннан бар. Басқа ID енгізіңіз.")
        if errors:
            raise ValidationError(errors)
        while not code:
            candidate = f"EQ-{secrets.token_hex(3).upper()}"
            if not self.equipment.code_exists(candidate):
                code = candidate
        profile = diagnostics.profile_for("", category)
        now = utc_now()
        with self.db.transaction() as conn:
            equipment_id = self.equipment.insert(
                code=code, name=device, model=model, category=category, kind=profile.title, profile=profile.key,
                created_by=actor.id, created_at=now, conn=conn,
            )
            record_id = self.repo.insert(
                conn, user_id=actor.id, operator_name=actor.full_name, equipment_id=equipment_id, performed_at=now,
                parameters="{}", result="Сигнал күтілуде", details="{}", status="pending",
            )
        return self.repo.get(record_id)

    def evaluate(self, actor: User, equipment_id: int, values: dict, margin=diagnostics.DEFAULT_MARGIN,
                 advanced=False):
        """Run the diagnostic rules (no persistence). Advanced mode needs the engineering permission."""
        require(actor, Perm.DIAG_RUN)
        if advanced:
            require(actor, Perm.DIAG_ADVANCED)
        else:
            margin = diagnostics.DEFAULT_MARGIN
        equipment = self.equipment.get(equipment_id)
        if equipment is None:
            raise NotFound("Жабдық табылмады.")
        profile = diagnostics.profile_for(equipment.profile, equipment.category)
        try:
            return profile, diagnostics.evaluate(profile, values, margin, advanced)
        except ValueError as error:
            raise ValidationError(f"Өлшем мәндері жарамсыз: {error}") from error

    def save_test(self, actor: User, equipment_id: int, values: dict, margin=diagnostics.DEFAULT_MARGIN,
                  advanced=False, notes="") -> HistoryRecord:
        """Re-evaluate on the server side and store the result, so a saved status always matches its inputs."""
        require(actor, Perm.REPORT_SAVE)
        profile, outcome = self.evaluate(actor, equipment_id, values, margin, advanced)
        if not advanced:
            margin = diagnostics.DEFAULT_MARGIN
        specs = profile.specs(advanced)
        details = dict(outcome.as_dict(), profile=profile.key, advanced=advanced, margin=margin)
        with self.db.transaction() as conn:
            record_id = self.repo.insert(
                conn, user_id=actor.id, operator_name=actor.full_name, equipment_id=equipment_id,
                performed_at=utc_now(), parameters=dumps({s.key: float(values[s.key]) for s in specs}),
                result=outcome.summary, details=dumps(details), status=outcome.status, notes=notes.strip()[:500],
            )
        return self.repo.get(record_id)

    def update(self, actor: User, record_id: int, *, notes: str, name: str | None = None, model: str | None = None):
        record = self.get(actor, record_id)
        if not self._editable(actor, record):
            raise PermissionDenied("Бұл жазбаны өңдеуге рұқсатыңыз жоқ.")
        equipment = self.equipment.get(record.equipment_id)
        errors = []
        rename = name is not None and (name.strip(), (model or "").strip()) != (equipment.name, equipment.model)
        if rename:
            if not can_rename_equipment(actor, equipment):
                raise PermissionDenied("Жабдық атауын тек оны тіркеген пайдаланушы немесе әкімші өзгерте алады.")
            if not name.strip() or not (model or "").strip() or len(name) > 80 or len(model or "") > 80:
                errors.append("Құрылғы атауы мен моделін енгізіңіз (80 таңбаға дейін).")
        if len(notes) > 500:
            errors.append("Ескерту 500 таңбадан аспауы керек.")
        if errors:
            raise ValidationError(errors)
        with self.db.transaction() as conn:
            if rename:
                self.equipment.rename(equipment.id, name.strip(), model.strip(), conn=conn)
            self.repo.update_notes(record_id, notes.strip(), conn=conn)
        return self.repo.get(record_id)

    def delete(self, actor: User, record_id: int):
        record = self.get(actor, record_id)
        if not self._editable(actor, record):
            raise PermissionDenied("Бұл жазбаны жоюға рұқсатыңыз жоқ.")
        self.repo.delete(record_id)


# ---------------------------------------------------------------- statistics & settings

class StatsService:
    def __init__(self, users: UserRepository, history: HistoryRepository):
        self.users, self.history = users, history

    def system(self, actor: User) -> dict:
        require(actor, Perm.SYSTEM_STATS)
        counts = self.history.counts("all", None)
        finished = counts["success"] + counts["warning"] + counts["failed"]
        by_role = self.users.counts_by_role()
        return {
            "users_total": self.users.count(),
            "users_active": self.users.count_active(),
            "users_by_role": {role: by_role.get(role, 0) for role in Role},
            "tests_total": sum(counts.values()),
            "tests_week": self.history.since_count(utc_now() - timedelta(days=7)),
            "counts": counts,
            "success_rate": round(100 * counts["success"] / finished) if finished else None,
            "top_operators": self.history.top_operators(),
        }


class SettingsService:
    def __init__(self, repo: SettingsRepository):
        self.repo = repo

    def get_all(self, actor: User) -> dict:
        require(actor, Perm.SYSTEM_SETTINGS)
        return self.repo.all()

    def save(self, actor: User, values: dict):
        require(actor, Perm.SYSTEM_SETTINGS)
        errors, clean = [], {}
        for key, value in values.items():
            if key not in DEFAULT_SETTINGS:
                errors.append(f"Белгісіз параметр: {key}")
            elif key == "registration_open":
                clean[key] = "1" if value in (True, "1", 1) else "0"
            else:
                low, high = SETTING_LIMITS[key]
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    number = None
                if number is None or not low <= number <= high:
                    errors.append(f"{key}: {low}–{high} аралығындағы бүтін сан енгізіңіз.")
                else:
                    clean[key] = str(number)
        if errors:
            raise ValidationError(errors)
        for key, value in clean.items():
            self.repo.set(key, value)


@dataclass
class Services:
    db: Database
    auth: AuthService
    users: UserService
    equipment: EquipmentService
    history: HistoryService
    stats: StatsService
    settings: SettingsService


def build_services(db: Database | None = None) -> Services:
    db = db or Database()
    user_repo, session_repo, settings_repo = UserRepository(db), SessionRepository(db), SettingsRepository(db)
    equipment_repo, history_repo = EquipmentRepository(db), HistoryRepository(db)
    auth = AuthService(db, user_repo, session_repo, settings_repo)
    return Services(
        db=db, auth=auth, users=UserService(user_repo, session_repo, auth),
        equipment=EquipmentService(equipment_repo), history=HistoryService(history_repo, equipment_repo, db),
        stats=StatsService(user_repo, history_repo), settings=SettingsService(settings_repo),
    )
