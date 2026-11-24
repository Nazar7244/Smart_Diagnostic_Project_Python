import os
from pathlib import Path

APP_NAME = "SmartDiagnost PRO"
APP_VERSION = "3.0"

# The first four are the original SmartDiagnost categories (order preserved);
# the last one covers the car-engine digital twin.
CATEGORIES = (
    "Электр қозғалтқышы",
    "Электр құралдары",
    "Газ турбинасы",
    "Тұрмыстық техника",
    "Автокөлік қозғалтқышы",
)


def data_dir() -> Path:
    """Per-user folder for the SQLite database and the remember-me token.

    SMARTDIAGNOST_HOME overrides the location (used by the tests).
    """
    override = os.getenv("SMARTDIAGNOST_HOME", "").strip()
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming") / "SmartDiagnostPRO"
    else:
        base = Path.home() / ".smartdiagnost-pro"
    base.mkdir(parents=True, exist_ok=True)
    return base


def database_path() -> Path:
    return data_dir() / "smartdiagnost.db"
