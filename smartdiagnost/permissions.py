from enum import Enum


class Role(str, Enum):
    ADMIN = "administrator"
    MECHANIC = "mechanic"
    ENGINEER = "engineer"
    GUEST = "guest"


ROLE_LABELS = {
    Role.ADMIN: "Әкімші",
    Role.MECHANIC: "Механик",
    Role.ENGINEER: "Инженер",
    Role.GUEST: "Қонақ",
}

# Roles anyone may pick when registering themselves. Administrator and Engineer
# (advanced tools) can only be granted by an existing administrator.
PUBLIC_ROLES = (Role.MECHANIC, Role.GUEST)


class Perm(str, Enum):
    DIAG_ENGINE = "diagnostics.engine"          # open the engine diagnostics workspace
    DIAG_EQUIPMENT = "diagnostics.equipment"    # open the equipment diagnostics workspace
    DIAG_RUN = "diagnostics.run"                # run diagnostic tests / AI analysis / record signals
    DIAG_ADVANCED = "diagnostics.advanced"      # engineering lab: extended parameters, tolerance control
    MEASUREMENTS_VIEW = "measurements.view"     # technical measurements and trends
    REPORT_SAVE = "reports.save"
    REPORT_EXPORT = "reports.export"
    REPORT_TECHNICAL = "reports.technical"
    HISTORY_OWN = "history.own"
    HISTORY_ALL = "history.all"
    HISTORY_DEMO = "history.demo"               # sample results only
    HISTORY_EDIT = "history.edit"               # edit/delete (own records unless HISTORY_ALL)
    USERS_MANAGE = "users.manage"
    SYSTEM_STATS = "system.stats"
    SYSTEM_SETTINGS = "system.settings"
    DEMO_MODE = "demo.mode"


_MECHANIC = frozenset({
    Perm.DIAG_ENGINE, Perm.DIAG_EQUIPMENT, Perm.DIAG_RUN,
    Perm.REPORT_SAVE, Perm.REPORT_EXPORT,
    Perm.HISTORY_OWN, Perm.HISTORY_EDIT,
})
_ENGINEER = _MECHANIC | {Perm.DIAG_ADVANCED, Perm.MEASUREMENTS_VIEW, Perm.REPORT_TECHNICAL}
_ADMIN = frozenset(set(Perm) - {Perm.DEMO_MODE})  # sees every report, including the demo samples
_GUEST = frozenset({Perm.DEMO_MODE, Perm.HISTORY_DEMO})

ROLE_PERMISSIONS = {
    Role.ADMIN: _ADMIN,
    Role.ENGINEER: _ENGINEER,
    Role.MECHANIC: _MECHANIC,
    Role.GUEST: _GUEST,
}


def role_can(role, perm) -> bool:
    return Perm(perm) in ROLE_PERMISSIONS[Role(role)]
