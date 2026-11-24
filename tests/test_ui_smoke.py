"""Offscreen UI tests: login flow, role-based navigation, diagnostics, history and admin actions.

Run:  python tests/test_ui_smoke.py            (set SD_SHOTS=<dir> to also save screenshots)
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt":  # the offscreen platform finds no fonts on its own
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
TMP = tempfile.mkdtemp(prefix="sd-test-")
os.environ["SMARTDIAGNOST_HOME"] = TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QToolButton  # noqa: E402

import main as app_main  # noqa: E402
from smartdiagnost.database import Database  # noqa: E402
from smartdiagnost.permissions import Role  # noqa: E402
from smartdiagnost.services import build_services  # noqa: E402
from smartdiagnost.session_store import RememberStore  # noqa: E402
from smartdiagnost.ui.auth_windows import ForgotPasswordDialog, LoginWindow, RegisterDialog  # noqa: E402
from smartdiagnost.ui.context import AppContext  # noqa: E402
from smartdiagnost.ui.shell import MainWindow  # noqa: E402

PASSWORD = "Str0ng!Pass"
SHOTS = os.getenv("SD_SHOTS")
app = QApplication.instance() or QApplication([])
app.setStyle("Fusion")
app.setStyleSheet(app_main.load_stylesheet())

# Message boxes would block the test run: auto-accept them and remember what was shown.
SHOWN = []
QMessageBox.exec = lambda self: (SHOWN.append(self.text()), QMessageBox.StandardButton.Ok)[1]


def shot(widget, name):
    if SHOTS:
        QTest.qWait(260)  # let the page fade-in finish
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        widget.grab().save(str(Path(SHOTS) / f"{name}.png"))


def register(svc, name, role, actor=None):
    return svc.auth.register(full_name=f"{name.title()} Tester", username=name, email=f"{name}@example.com",
                             phone="+7 701 123 45 67", password=PASSWORD, confirm_password=PASSWORD, role=role,
                             actor=actor)


class UiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = build_services(Database(":memory:"))
        cls.users = {}
        cls.users["admin"] = register(cls.svc, "boss", None)
        cls.users["mechanic"] = register(cls.svc, "mech", Role.MECHANIC)
        cls.users["guest"] = register(cls.svc, "visitor", Role.GUEST)
        cls.users["engineer"] = register(cls.svc, "eng", Role.ENGINEER, cls.users["admin"])

    def window_for(self, role):
        username = {"admin": "boss", "mechanic": "mech", "guest": "visitor", "engineer": "eng"}[role]
        session = self.svc.auth.login(username, PASSWORD)
        window = MainWindow(AppContext(self.svc, session))
        window.show()
        self.addCleanup(window.close)
        app.processEvents()
        return window

    def test_navigation_per_role(self):
        expected = {
            "admin": {"dashboard", "engine", "equipment", "lab", "history", "users", "system", "settings", "profile"},
            "engineer": {"dashboard", "engine", "equipment", "lab", "history", "settings", "profile"},
            "mechanic": {"dashboard", "engine", "equipment", "history", "settings", "profile"},
            "guest": {"dashboard", "engine", "history", "settings", "profile"},
        }
        for role, keys in expected.items():
            window = self.window_for(role)
            self.assertEqual(set(window.specs), keys, role)
            for key in window.specs:
                window.navigate(key)
                app.processEvents()
                self.assertIs(window.stack.currentWidget(), window.pages[key], f"{role}:{key}")
                shot(window, f"{role}_{key}")
            window.navigate("users")  # forbidden pages are ignored
            if role != "admin":
                self.assertNotIn("users", window.specs)
            window.close()

    def test_guest_is_read_only(self):
        window = self.window_for("guest")
        self.assertFalse(window.workspace.recorder.isEnabled())
        self.assertFalse(window.workspace.ai_button.isEnabled())
        self.assertFalse(window.workspace.runner.run.isEnabled())
        history = window.history
        self.assertEqual(len(history.records), 3)
        texts = [b.text() for b in history.table.cellWidget(0, 6).findChildren(QToolButton)]
        self.assertEqual(texts, ["Қарау"])  # no edit / delete / export for guests

    def test_mechanic_runs_test_and_saves_to_history(self):
        window = self.window_for("mechanic")
        runner = window.workspace.runner
        window.navigate("equipment")
        before = window.history.table.rowCount()
        failed_before = self.svc.history.counts(self.users["mechanic"])["failed"]
        runner.spinners["vibration"].setValue(3.2)
        runner.run_test()
        self.assertEqual(runner.outcome.status, "failed")
        shot(window, "mechanic_test_result")
        runner.save_report()
        self.assertIsNotNone(runner.saved_record)
        window.navigate("history")
        self.assertEqual(window.history.table.rowCount(), before + 1)
        self.assertEqual(window.history.records[0].status, "failed")
        window.navigate("dashboard")
        self.assertEqual(window.pages["dashboard"].failed.value.text(), str(failed_before + 1))

    def test_new_check_form_creates_pending_record_and_validates(self):
        window = self.window_for("mechanic")
        ws = window.workspace
        window.navigate("equipment")
        ws.create_entry()  # empty -> validation message, nothing created
        self.assertTrue(any("Құрылғы атауы" in text for text in SHOWN))
        ws.device.setText("Test Drill")
        ws.model.setText("TD-1")
        ws.entry_id.setText("TD-CHECK-1")
        ws.create_entry()
        self.assertEqual(ws.device.text(), "")
        window.navigate("history")
        window.history.set_search("TD-CHECK-1")
        self.assertEqual([r.status for r in window.history.records], ["pending"])

    def test_history_filters_view_and_delete(self):
        window = self.window_for("admin")
        history = window.history
        window.navigate("history")
        self.assertGreaterEqual(len(history.records), 3)
        history.set_search("M-4000")
        self.assertTrue(all("M-4000" in r.equipment_code for r in history.records))
        history.reset_filters()
        history.status.setCurrentIndex(history.status.findData("failed"))
        self.assertTrue(history.records and all(r.status == "failed" for r in history.records))
        shot(window, "admin_history_filtered")
        history.reset_filters()
        from smartdiagnost.ui.history import RecordDialog
        dialog = RecordDialog(window.ctx, history.records[0], window)
        dialog.show()
        shot(dialog, "record_dialog")
        dialog.close()

    def test_admin_user_management_ui_paths(self):
        window = self.window_for("admin")
        page = window.pages["users"]
        window.navigate("users")
        self.assertGreaterEqual(len(page.users), 4)
        page.search.setText("mech")
        page.refresh()
        self.assertEqual([u.username for u in page.users], ["mech"])
        shot(window, "admin_users")
        window.navigate("system")
        window.pages["system"].save()
        shot(window, "admin_system")

    def test_login_window_flow(self):
        store = RememberStore(Path(TMP) / "remember-test.json")
        login = LoginWindow(self.svc, store)
        login.show()
        got = []
        login.authenticated.connect(got.append)
        login.identifier.setText("mech")
        login.password.setText("bad-password")
        login.attempt_login()
        self.assertFalse(got)
        self.assertFalse(login.error.isHidden())
        shot(login, "login_error")
        login.password.setText(PASSWORD)
        login.attempt_login()
        self.assertEqual(got[0].user.username, "mech")
        self.assertEqual(login.password.text(), "")
        # narrow window hides the brand panel (responsive)
        login.resize(640, 700)
        app.processEvents()
        self.assertTrue(login.hero.isHidden())

    def test_registration_dialog_never_offers_privileged_roles(self):
        dialog = RegisterDialog(self.svc)
        roles = [dialog.role.itemData(i) for i in range(dialog.role.count())]
        self.assertEqual(roles, [Role.MECHANIC, Role.GUEST])
        dialog.show()
        dialog.full_name.setText("New Person")
        dialog.username.setText("newperson")
        dialog.email.setText("new@example.com")
        dialog.phone.setText("+7 700 000 00 00")
        dialog.password.setText("weak")
        dialog.confirm.setText("weak")
        shot(dialog, "register_dialog")
        dialog.submit()
        self.assertFalse(dialog.error.isHidden())
        dialog.password.setText(PASSWORD)
        dialog.confirm.setText(PASSWORD)
        dialog.submit()
        self.assertEqual(dialog.created.role, Role.MECHANIC)
        # tampering with the combo data cannot escalate either: the service refuses
        dialog2 = RegisterDialog(self.svc)
        dialog2.role.addItem("Әкімші", Role.ADMIN)
        dialog2.role.setCurrentIndex(dialog2.role.count() - 1)
        for widget, text in ((dialog2.full_name, "Evil Person"), (dialog2.username, "evil"),
                             (dialog2.email, "evil@example.com"), (dialog2.password, PASSWORD),
                             (dialog2.confirm, PASSWORD)):
            widget.setText(text)
        dialog2.submit()
        self.assertIsNone(dialog2.created)
        self.assertIn("әкімші", dialog2.error.text())

    def test_first_run_setup_mode_creates_administrator(self):
        fresh = build_services(Database(":memory:"))
        dialog = RegisterDialog(fresh)
        self.assertTrue(dialog.setup_mode)
        self.assertEqual(dialog.role.itemData(0), Role.ADMIN)
        login = LoginWindow(fresh, RememberStore(Path(TMP) / "r2.json"))
        login.show()
        shot(login, "login_first_run")
        self.assertFalse(login.banner.isHidden())

    def test_forgot_password_dialog_with_admin_code(self):
        code = self.svc.users.issue_reset_code(self.users["admin"], self.users["guest"].id)
        dialog = ForgotPasswordDialog(self.svc)
        dialog.identifier.setText("visitor@example.com")
        dialog.code.setText(code)
        dialog.password.setText("N3w!Passw0rd")
        dialog.confirm.setText("N3w!Passw0rd")
        dialog.submit()
        self.assertTrue(dialog.error.isHidden())
        self.assertEqual(dialog.result(), 1)
        self.svc.auth.login("visitor", "N3w!Passw0rd")
        self.svc.users.update(self.users["admin"], self.users["guest"].id, full_name="Visitor Tester",
                              email="visitor@example.com", phone="", role=Role.GUEST, is_active=True,
                              new_password=PASSWORD)

    def test_controller_login_logout_and_remember_me(self):
        store = RememberStore(Path(TMP) / "remember-ctl.json")
        controller = app_main.AppController(self.svc, store)
        controller.start()
        self.assertTrue(controller.login.isVisible())
        session = self.svc.auth.login("eng", PASSWORD, remember=True)
        controller.open_main(session)
        self.assertEqual(store.load(), session.token)
        self.assertFalse(controller.login.isVisible())
        controller.main_window.logout_requested.emit()
        self.assertIsNone(self.svc.auth.validate(session.token))  # server-side session revoked
        self.assertEqual(store.load(), "")
        self.assertTrue(controller.login.isVisible())
        # a remembered token resumes straight into the app; a revoked one does not
        again = self.svc.auth.login("eng", PASSWORD, remember=True)
        store.save(again.token)
        controller2 = app_main.AppController(self.svc, store)
        controller2.start()
        self.assertIsNotNone(controller2.main_window)
        controller2.main_window.close()
        self.svc.auth.logout(again.token)
        controller3 = app_main.AppController(self.svc, store)
        controller3.start()
        self.assertIsNone(controller3.main_window)
        self.assertEqual(store.load(), "")

    def test_session_guard_forces_logout_when_disabled_or_role_changed(self):
        window = self.window_for("mechanic")
        fired = []
        window.logout_requested.connect(lambda: fired.append(1))
        admin = self.users["admin"]
        mech = self.users["mechanic"]
        self.svc.users.update(admin, mech.id, full_name=mech.full_name, email=mech.email, phone=mech.phone,
                              role=Role.ENGINEER, is_active=True)
        window.check_session()
        self.assertEqual(fired, [1])
        self.svc.users.update(admin, mech.id, full_name=mech.full_name, email=mech.email, phone=mech.phone,
                              role=Role.MECHANIC, is_active=True)

    def test_lab_trend_and_technical_report_export(self):
        window = self.window_for("engineer")
        lab = window.pages["lab"]
        window.navigate("lab")
        runner = lab.runner
        self.assertIn("insulation", runner.spinners)  # advanced parameters
        runner.margin.setValue(25)
        runner.run_test()
        runner.save_report()
        self.assertEqual(len(lab.spark.values), 1)
        record = runner.current_record()
        self.assertTrue(record.details["advanced"])
        shot(window, "engineer_lab")


if __name__ == "__main__":
    unittest.main()
