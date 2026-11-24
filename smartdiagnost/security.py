"""Password hashing, token handling and input validation (pure stdlib)."""
import base64
import hashlib
import hmac
import os
import re
import secrets
import unicodedata

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
PBKDF2_ITERATIONS = 600_000
MAX_PASSWORD_LENGTH = 128

COMMON_PASSWORDS = frozenset({
    "password", "password1", "password123", "12345678", "123456789", "1234567890", "qwerty123",
    "qwertyuiop", "iloveyou", "admin123", "administrator", "letmein123", "welcome123", "abc12345",
    "11111111", "00000000", "qazwsxedc", "smartdiagnost", "diagnost123",
})


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _normalize(password: str) -> bytes:
    return unicodedata.normalize("NFKC", password).encode("utf-8")


def hash_password(password: str) -> str:
    """Salted scrypt hash (PBKDF2-SHA256 when scrypt is unavailable), self-describing format."""
    salt = os.urandom(16)
    data = _normalize(password)
    if hasattr(hashlib, "scrypt"):
        digest = hashlib.scrypt(data, salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024)
        return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"
    digest = hashlib.pbkdf2_hmac("sha256", data, salt, PBKDF2_ITERATIONS, dklen=32)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check. Malformed hashes simply fail."""
    try:
        data = _normalize(password)
        parts = stored.split("$")
        if parts[0] == "scrypt":
            _, n, r, p, salt, expected = parts
            digest = hashlib.scrypt(
                data, salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                dklen=32, maxmem=64 * 1024 * 1024,
            )
        elif parts[0] == "pbkdf2_sha256":
            _, iterations, salt, expected = parts
            digest = hashlib.pbkdf2_hmac("sha256", data, base64.b64decode(salt), int(iterations), dklen=32)
        else:
            return False
        return hmac.compare_digest(digest, base64.b64decode(expected))
    except (ValueError, TypeError, OverflowError, MemoryError):
        return False


_DUMMY_HASH = None


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check, so unknown accounts are not distinguishable by timing."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("timing-equalizer")
    verify_password(password, _DUMMY_HASH)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


_RESET_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_reset_code() -> str:
    raw = "".join(secrets.choice(_RESET_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_reset_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", code.upper())


# ---------------------------------------------------------------- validation

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")


def validate_full_name(value: str):
    value = value.strip()
    if not 2 <= len(value) <= 80 or any(ch in value for ch in "<>\n\r\t"):
        return "Толық атыңызды енгізіңіз (2–80 таңба)."
    return None


def validate_username(value: str):
    if not USERNAME_RE.fullmatch(value.strip()):
        return "Пайдаланушы аты 3–32 таңба: латын әріптері, сандар, _ . -"
    return None


def validate_email(value: str):
    value = value.strip()
    if len(value) > 254 or not EMAIL_RE.fullmatch(value):
        return "Электрондық пошта форматы дұрыс емес."
    return None


def validate_phone(value: str):
    """Phone is optional; when given it needs 7-15 digits (a leading + and common separators are allowed)."""
    value = value.strip()
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if not re.fullmatch(r"\+?[\d\s()\-]+", value) or not 7 <= len(digits) <= 15:
        return "Телефон нөмірі дұрыс емес (7–15 сан, + рұқсат етіледі)."
    return None


def validate_password(password: str, username: str = "", email: str = "", full_name: str = ""):
    """Return the list of unmet password rules (empty list means the password is acceptable)."""
    errors = []
    if len(password) < 8:
        errors.append("Құпиясөз кемінде 8 таңба болуы керек.")
    if len(password) > MAX_PASSWORD_LENGTH:
        errors.append(f"Құпиясөз {MAX_PASSWORD_LENGTH} таңбадан аспауы керек.")
    if not any(ch.islower() for ch in password):
        errors.append("Құпиясөзге кіші әріп қосыңыз.")
    if not any(ch.isupper() for ch in password):
        errors.append("Құпиясөзге бас әріп қосыңыз.")
    if not any(ch.isdigit() for ch in password):
        errors.append("Құпиясөзге сан қосыңыз.")
    if not any(not ch.isalnum() and not ch.isspace() for ch in password):
        errors.append("Құпиясөзге арнайы таңба қосыңыз (!@#$…).")
    lowered = password.casefold()
    if lowered in COMMON_PASSWORDS:
        errors.append("Құпиясөз тым оңай, басқасын таңдаңыз.")
    for secret in (username.strip(), email.split("@")[0].strip()):
        if len(secret) >= 3 and secret.casefold() in lowered:
            errors.append("Құпиясөзде пайдаланушы аты немесе email болмауы керек.")
            break
    return errors


def password_strength(password: str) -> int:
    """0 (empty/very weak) .. 4 (strong); used by the live meter in the registration form."""
    if not password:
        return 0
    score = sum((
        len(password) >= 8,
        len(password) >= 12,
        any(ch.islower() for ch in password) and any(ch.isupper() for ch in password),
        any(ch.isdigit() for ch in password) and any(not ch.isalnum() for ch in password),
    ))
    if password.casefold() in COMMON_PASSWORDS:
        score = min(score, 1)
    return score
