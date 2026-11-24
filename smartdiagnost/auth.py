"""Authentication: registration, login/logout, sessions, password change and reset."""
from datetime import timedelta

from . import security
from .errors import AuthError, PermissionDenied, ValidationError
from .models import Session, User, parse_iso, utc_now
from .permissions import PUBLIC_ROLES, Perm, Role
from .repositories import SessionRepository, SettingsRepository, UserRepository, row_to_user

GENERIC_LOGIN_ERROR = "Пайдаланушы аты (email) немесе құпиясөз дұрыс емес."
RESET_CODE_MINUTES = 30
RESET_MAX_ATTEMPTS = 5


def require(actor: User | None, perm: Perm):
    if actor is None or not actor.can(perm):
        raise PermissionDenied()


def validate_profile_fields(full_name, username, email, phone) -> list:
    checks = (
        security.validate_full_name(full_name), security.validate_username(username),
        security.validate_email(email), security.validate_phone(phone),
    )
    return [error for error in checks if error]


class AuthService:
    def __init__(self, db, users: UserRepository, sessions: SessionRepository, settings: SettingsRepository):
        self.db, self.users, self.sessions, self.settings = db, users, sessions, settings

    # ------------------------------------------------------------ registration
    def needs_setup(self) -> bool:
        """True until the first administrator exists (first run)."""
        return self.users.count_admins() == 0

    def registration_open(self) -> bool:
        return self.settings.get("registration_open") == "1"

    def register(self, *, full_name, username, email, phone="", password, confirm_password, role=None,
                 actor: User | None = None) -> User:
        """Create an account.

        Without `actor` this is self-registration: only PUBLIC_ROLES can be chosen, and the very
        first account of a fresh installation becomes the administrator. Any other role (including
        administrator) requires an `actor` holding USERS_MANAGE.
        """
        if actor is None:
            if self.needs_setup():
                target_role = Role.ADMIN
            else:
                if not self.registration_open():
                    raise PermissionDenied("Тіркелу әкімшімен уақытша жабылған.")
                target_role = Role(role) if role else Role.MECHANIC
                if target_role not in PUBLIC_ROLES:
                    raise PermissionDenied("Бұл рөлді тек әкімші тағайындай алады.")
        else:
            require(actor, Perm.USERS_MANAGE)
            target_role = Role(role) if role else Role.MECHANIC

        errors = validate_profile_fields(full_name, username, email, phone)
        errors += security.validate_password(password, username, email, full_name)
        if password != confirm_password:
            errors.append("Құпиясөздер сәйкес келмейді.")
        errors += self.users.conflicts(username, email)
        if errors:
            raise ValidationError(errors)

        user_id = self.users.insert(
            full_name=full_name, username=username, email=email, phone=phone,
            password_hash=security.hash_password(password), role=target_role, created_at=utc_now(),
        )
        return self.users.get(user_id)

    # ------------------------------------------------------------ login / sessions
    def _open_session(self, user: User, remember: bool) -> Session:
        now = utc_now()
        lifetime = (
            timedelta(days=int(self.settings.get("remember_days")))
            if remember else timedelta(hours=int(self.settings.get("session_hours")))
        )
        token = security.new_token()
        self.sessions.create(user.id, security.hash_token(token), now, now + lifetime, remember)
        self.sessions.purge(now - timedelta(days=1))
        return Session(user=user, token=token, expires_at=now + lifetime, remember=remember)

    def login(self, identifier: str, password: str, remember: bool = False) -> Session:
        identifier = identifier.strip()
        if not identifier or not password:
            raise AuthError("Пайдаланушы атын және құпиясөзді енгізіңіз.")
        row = self.users.find_row(identifier)
        now = utc_now()
        if row is None:
            security.burn_password_check(password)
            raise AuthError(GENERIC_LOGIN_ERROR)

        locked_until = parse_iso(row["locked_until"])
        if locked_until and locked_until > now:
            minutes = max(1, int((locked_until - now).total_seconds() // 60) + 1)
            raise AuthError(f"Тіркелгі уақытша бұғатталды. {minutes} минуттан кейін қайталаңыз.")

        if not security.verify_password(password, row["password_hash"]):
            attempts = row["failed_attempts"] + 1
            limit = int(self.settings.get("max_failed_attempts"))
            lock = None
            if attempts >= limit:
                lock, attempts = now + timedelta(minutes=int(self.settings.get("lockout_minutes"))), 0
            self.users.record_failure(row["id"], attempts, lock)
            raise AuthError(GENERIC_LOGIN_ERROR)

        if not row["is_active"]:
            raise AuthError("Тіркелгі өшірілген. Әкімшіге хабарласыңыз.")
        self.users.record_success(row["id"], now)
        return self._open_session(self.users.get(row["id"]), remember)

    def resume(self, token: str) -> Session | None:
        """Restore a remembered session; None if the token is unknown, expired, revoked or the user is disabled."""
        user = self.validate(token)
        if user is None:
            return None
        found = self.sessions.find_valid(security.hash_token(token), utc_now())
        return Session(user=user, token=token, expires_at=parse_iso(found["expires_at"]), remember=bool(found["remember"]))

    def validate(self, token: str) -> User | None:
        """Return the current, fresh user for a live session (touching it), or None."""
        if not token:
            return None
        token_hash, now = security.hash_token(token), utc_now()
        row = self.sessions.find_valid(token_hash, now)
        if row is None or not row["is_active"]:
            return None
        self.sessions.touch(token_hash, now)
        return row_to_user(row)

    def logout(self, token: str):
        if token:
            self.sessions.revoke(security.hash_token(token), utc_now())

    def active_session_count(self, user: User) -> int:
        return self.sessions.count_active(user.id, utc_now())

    def logout_other_sessions(self, user: User, token: str):
        self.sessions.revoke_user(user.id, utc_now(), except_hash=security.hash_token(token))

    # ------------------------------------------------------------ profile / passwords
    def update_profile(self, user: User, *, full_name, email, phone="") -> User:
        if user.role is Role.GUEST:
            raise PermissionDenied("Қонақ профилін өзгерте алмайды.")
        errors = validate_profile_fields(full_name, user.username, email, phone)
        errors += self.users.conflicts(user.username, email, exclude_id=user.id)
        if errors:
            raise ValidationError(errors)
        self.users.update(user.id, full_name=full_name.strip(), email=email.strip(), phone=phone.strip())
        return self.users.get(user.id)

    def change_password(self, user: User, current: str, new: str, confirm: str, token: str = ""):
        row = self.users.get_row(user.id)
        if row is None or not security.verify_password(current, row["password_hash"]):
            raise ValidationError("Ағымдағы құпиясөз дұрыс емес.")
        errors = security.validate_password(new, user.username, user.email, user.full_name)
        if new != confirm:
            errors.append("Құпиясөздер сәйкес келмейді.")
        if security.verify_password(new, row["password_hash"]):
            errors.append("Жаңа құпиясөз ағымдағыдан өзгеше болуы керек.")
        if errors:
            raise ValidationError(errors)
        self.users.set_password(user.id, security.hash_password(new))
        if token:
            self.logout_other_sessions(user, token)

    def issue_reset_code(self, actor: User, user_id: int) -> str:
        """Administrator-issued one-time code (valid 30 min) that lets the user choose a new password."""
        require(actor, Perm.USERS_MANAGE)
        if self.users.get(user_id) is None:
            raise ValidationError("Пайдаланушы табылмады.")
        code = security.new_reset_code()
        self.users.set_reset(
            user_id, security.hash_password(security.normalize_reset_code(code)),
            utc_now() + timedelta(minutes=RESET_CODE_MINUTES),
        )
        return code

    def reset_password(self, identifier: str, code: str, new: str, confirm: str):
        failure = "Деректер немесе код дұрыс емес, не мерзімі өтті."
        row = self.users.find_row(identifier.strip()) if identifier.strip() else None
        normalized = security.normalize_reset_code(code)
        expires = parse_iso(row["reset_expires_at"]) if row else None
        usable = bool(
            row and row["reset_code_hash"] and expires and expires > utc_now()
            and row["reset_attempts"] < RESET_MAX_ATTEMPTS
        )
        if not usable:
            security.burn_password_check(normalized)
            raise AuthError(failure)
        if not security.verify_password(normalized, row["reset_code_hash"]):
            self.users.bump_reset_attempts(row["id"])
            raise AuthError(failure)
        errors = security.validate_password(new, row["username"], row["email"], row["full_name"])
        if new != confirm:
            errors.append("Құпиясөздер сәйкес келмейді.")
        if errors:
            raise ValidationError(errors)
        self.users.set_password(row["id"], security.hash_password(new))
        self.sessions.revoke_user(row["id"], utc_now())
