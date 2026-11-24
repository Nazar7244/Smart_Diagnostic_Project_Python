"""Rule-based diagnostic evaluation (no Qt, no database).

A profile lists the parameters measured on a kind of equipment and their nominal
operating range. Every measured value is compared against its range:

* inside the range                          -> OK
* outside, by <= `margin` of the range span -> WARNING
* outside, by  > `margin` of the range span -> CRITICAL

The nominal ranges below are illustrative defaults for the demo equipment that
ships with SmartDiagnost. They are NOT manufacturer specifications.
"""
import math
from dataclasses import dataclass, field
from enum import Enum

from .config import CATEGORIES

DEFAULT_MARGIN = 0.10
WARNING_PENALTY, CRITICAL_PENALTY = 8, 25


class State(str, Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


STATE_LABELS = {State.OK: "Қалыпты", State.WARNING: "Ескерту", State.CRITICAL: "Ауытқу"}


@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    unit: str
    low: float
    high: float
    default: float
    decimals: int = 1
    advanced: bool = False


@dataclass(frozen=True)
class Profile:
    key: str
    title: str
    params: tuple

    def specs(self, advanced=False):
        return [spec for spec in self.params if advanced or not spec.advanced]


PROFILES = {
    profile.key: profile
    for profile in (
        Profile("motor", "Электр қозғалтқышы", (
            ParamSpec("temperature", "Температура", "°C", 20, 75, 45),
            ParamSpec("vibration", "Діріл", "G", 0, 2.0, 1.2, 2),
            ParamSpec("speed", "Жылдамдық", "RPM", 1400, 1600, 1500, 0),
            ParamSpec("torque", "Айналу моменті", "N·m", 10, 15, 12.8),
            ParamSpec("field", "Магниттік өріс", "T", 0.35, 0.50, 0.42, 2),
            ParamSpec("insulation", "Оқшаулама кедергісі", "MΩ", 100, 1000, 450, 0, True),
            ParamSpec("imbalance", "Ток теңсіздігі", "%", 0, 5, 1.8, 1, True),
        )),
        Profile("automotive", "Автокөлік қозғалтқышы", (
            ParamSpec("coolant", "Салқындатқыш температурасы", "°C", 80, 105, 88),
            ParamSpec("oil_pressure", "Май қысымы", "бар", 2.0, 5.0, 3.2),
            ParamSpec("rpm", "Айналым жиілігі", "RPM", 700, 6000, 2800, 0),
            ParamSpec("oil_temp", "Май температурасы", "°C", 80, 120, 95, 0, True),
            ParamSpec("battery", "Бортжелі кернеуі", "V", 13.2, 14.8, 14.1, 1, True),
        )),
        Profile("turbofan", "Турбожелдеткіш / газ турбинасы", (
            ParamSpec("fan_speed", "Желдеткіш айналымы", "RPM", 2500, 5000, 3800, 0),
            ParamSpec("gas_temp", "Шығатын газ температурасы", "°C", 400, 850, 650, 0),
            ParamSpec("vibration", "Діріл", "G", 0, 2.5, 1.8, 2),
            ParamSpec("oil_pressure", "Май қысымы", "бар", 2.5, 6.0, 4.1, 1, True),
            ParamSpec("oil_temp", "Май температурасы", "°C", 60, 110, 85, 0, True),
        )),
        Profile("power_tool", "Электр құралы", (
            ParamSpec("temperature", "Корпус температурасы", "°C", 20, 70, 38),
            ParamSpec("vibration", "Діріл", "G", 0, 2.5, 1.0, 2),
            ParamSpec("current", "Тоқ тұтыну", "A", 1.0, 6.5, 3.4),
            ParamSpec("noise", "Шу деңгейі", "dB(A)", 60, 95, 82, 0, True),
            ParamSpec("insulation", "Оқшаулама кедергісі", "MΩ", 2, 500, 80, 0, True),
        )),
        Profile("appliance", "Тұрмыстық техника", (
            ParamSpec("temperature", "Температура", "°C", 20, 80, 40),
            ParamSpec("vibration", "Діріл", "G", 0, 1.5, 0.6, 2),
            ParamSpec("noise", "Шу деңгейі", "dB(A)", 30, 70, 52, 0),
            ParamSpec("current", "Тоқ тұтыну", "A", 0.3, 10, 2.5, 1, True),
        )),
    )
}

CATEGORY_PROFILE = {
    CATEGORIES[0]: "motor",
    CATEGORIES[1]: "power_tool",
    CATEGORIES[2]: "turbofan",
    CATEGORIES[3]: "appliance",
    CATEGORIES[4]: "automotive",
}


def profile_for(profile_key: str = "", category: str = "") -> Profile:
    key = profile_key if profile_key in PROFILES else CATEGORY_PROFILE.get(category, "appliance")
    return PROFILES[key]


@dataclass(frozen=True)
class Finding:
    key: str
    label: str
    unit: str
    value: float
    low: float
    high: float
    state: State
    deviation: float      # fraction of the range span outside the range (0 when inside)
    message: str

    def as_dict(self):
        data = {name: getattr(self, name) for name in self.__dataclass_fields__}
        data["state"] = self.state.value
        return data


@dataclass
class Outcome:
    status: str           # success | warning | failed
    health: int           # 0..100
    summary: str
    findings: list = field(default_factory=list)

    def as_dict(self):
        return {
            "status": self.status,
            "health": self.health,
            "summary": self.summary,
            "findings": [finding.as_dict() for finding in self.findings],
        }


def _fmt(value, decimals=2):
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".") if decimals else f"{value:.0f}"


def evaluate(profile: Profile, values: dict, margin: float = DEFAULT_MARGIN, advanced: bool = False) -> Outcome:
    """Evaluate measured `values` ({param key: number}) against the profile."""
    if not 0 < margin <= 1:
        raise ValueError("margin must be in (0, 1]")
    findings = []
    for spec in profile.specs(advanced):
        if spec.key not in values:
            raise ValueError(f"missing value: {spec.key}")
        value = float(values[spec.key])
        if not math.isfinite(value):
            raise ValueError(f"invalid value: {spec.key}")
        span = (spec.high - spec.low) or 1.0
        if value < spec.low:
            deviation = (spec.low - value) / span
            side = f"төменгі шектен ({_fmt(spec.low)} {spec.unit}) төмен"
        elif value > spec.high:
            deviation = (value - spec.high) / span
            side = f"жоғарғы шектен ({_fmt(spec.high)} {spec.unit}) жоғары"
        else:
            deviation, side = 0.0, ""
        if deviation == 0:
            state, message = State.OK, "Нормалық диапазонда"
        elif deviation <= margin:
            state, message = State.WARNING, f"Шектен сәл ауытқыды: {side}"
        else:
            state, message = State.CRITICAL, f"Айтарлықтай ауытқу: {side}"
        findings.append(Finding(spec.key, spec.label, spec.unit, value, spec.low, spec.high, state, round(deviation, 4), message))

    critical = [f for f in findings if f.state is State.CRITICAL]
    warnings = [f for f in findings if f.state is State.WARNING]
    health = max(0, 100 - CRITICAL_PENALTY * len(critical) - WARNING_PENALTY * len(warnings))
    if critical:
        status = "failed"
        summary = "Ақау белгілері: " + ", ".join(f.label for f in critical)
    elif warnings:
        status = "warning"
        summary = "Ескерту: " + ", ".join(f.label for f in warnings)
    else:
        status = "success"
        summary = "Қалыпты · ауытқулар анықталмады"
    return Outcome(status, health, f"{summary} · денсаулық {health}%", findings)
