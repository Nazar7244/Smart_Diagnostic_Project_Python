"""SmartDiagnost PRO entry point.

The application always opens on the login screen (or resumes a "remember me" session).
The original diagnostic workspace now lives in smartdiagnost/ui/workspace.py.
"""
import sys
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from desktop_visuals import ASSETS, PUBLIC
from smartdiagnost.config import APP_NAME
from smartdiagnost.database import Database
from smartdiagnost.services import build_services
from smartdiagnost.session_store import RememberStore
from smartdiagnost.ui.auth_windows import LoginWindow
from smartdiagnost.ui.context import AppContext
from smartdiagnost.ui.shell import MainWindow


class AppController(QObject):
    """Owns the login window and the signed-in window and moves between them."""

    def __init__(self, services, store: RememberStore):
        super().__init__()
        self.services, self.store = services, store
        self.session = None
        self.main_window = None
        self.login = LoginWindow(services, store)
        self.login.authenticated.connect(self.open_main)

    def start(self):
        token = self.store.load()
        session = self.services.auth.resume(token) if token else None
        if token and session is None:
            self.store.clear()  # stale / revoked / expired token
        if session is not None:
            self.open_main(session)
        else:
            self.login.show()

    def open_main(self, session):
        if session.remember:
            self.store.save(session.token)
        else:
            self.store.clear()
        self.session = session
        context = AppContext(self.services, session)
        self.main_window = MainWindow(context)
        self.main_window.logout_requested.connect(self.sign_out)
        self.main_window.show()
        self.login.hide()

    def sign_out(self):
        if self.session is not None:
            self.services.auth.logout(self.session.token)
        self.store.clear()
        self.session = None
        window, self.main_window = self.main_window, None
        self.login.reset_form()
        self.login.show()
        if window is not None:
            window.close()
            window.deleteLater()

    def shutdown(self):
        """App is quitting: end sessions that were not marked "remember me"."""
        if self.session is not None and not self.session.remember:
            self.services.auth.logout(self.session.token)


def load_stylesheet() -> str:
    """desktop.qss with the asset placeholders resolved to absolute paths."""
    stylesheet = Path(__file__).with_name("desktop.qss").read_text(encoding="utf-8")
    for placeholder, asset in (("COMBO_ARROW", "chevron.svg"), ("CHECK_MARK", "check.svg"),
                               ("CHEVRON_UP", "chevron-up.svg")):
        stylesheet = stylesheet.replace(placeholder, (ASSETS / asset).as_posix())
    return stylesheet


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(PUBLIC / "favicon.png")))
    app.setStyleSheet(load_stylesheet())
    try:
        services = build_services(Database())
    except Exception as error:  # noqa: BLE001 - corrupt/locked database file
        QMessageBox.critical(None, APP_NAME, f"Деректер қорын ашу мүмкін болмады:\n{error}")
        return 1
    controller = AppController(services, RememberStore())
    app.aboutToQuit.connect(controller.shutdown)
    controller.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
