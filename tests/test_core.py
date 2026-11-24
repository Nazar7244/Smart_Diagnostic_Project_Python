import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from smartdiagnost import diagnostics, security  # noqa: E402
from smartdiagnost.database import Database  # noqa: E402
from smartdiagnost.errors import AuthError, NotFound, PermissionDenied, ValidationError  # noqa: E402
from smartdiagnost.permissions import Perm, Role, role_can  # noqa: E402
from smartdiagnost.services import build_services  # noqa: E402

GOOD = "Str0ng!Pass"


def make_user(svc, name, role, actor=None):
    return svc.auth.register(
        full_name=f"{name} Tester", username=name, email=f"{name}@example.com", phone="+7 701 123 45 67",
        password=GOOD, confirm_password=GOOD, role=role, actor=actor,
    )


class CoreTest(unittest.TestCase):
    def setUp(self):
        self.svc = build_services(Database(":memory:"))
        self.admin = make_user(self.svc, "boss", None)  # first account becomes administrator
        self.mech = make_user(self.svc, "mech", Role.MECHANIC)
        self.guest = make_user(self.svc, "visitor", Role.GUEST)
        self.eng = make_user(self.svc, "eng", Role.ENGINEER, actor=self.admin)

    # --- passwords / registration
    def test_hash_is_salted_and_verifies(self):
        first, second = security.hash_password(GOOD), security.hash_password(GOOD)
        self.assertNotEqual(first, second)
        self.assertNotIn(GOOD, first)
        self.assertTrue(security.verify_password(GOOD, first))
        self.assertFalse(security.verify_password("wrong", first))
        self.assertFalse(security.verify_password(GOOD, "garbage"))

    def test_password_rules(self):
        for bad in ("Sh0rt!A", "alllowercase1!", "ALLUPPERCASE1!", "NoDigits!!", "NoSpecial123", "Password1"):
            self.assertTrue(security.validate_password(bad), bad)
        self.assertEqual(security.validate_password(GOOD), [])
        self.assertTrue(security.validate_password("Boss!Pass99", username="boss"))

    def test_first_user_is_admin_then_public_roles_only(self):
        self.assertEqual(self.admin.role, Role.ADMIN)
        self.assertFalse(self.svc.auth.needs_setup())
        with self.assertRaises(PermissionDenied):
            make_user(self.svc, "sneaky", Role.ADMIN)
        with self.assertRaises(PermissionDenied):
            make_user(self.svc, "sneaky2", Role.ENGINEER)
        self.assertEqual(make_user(self.svc, "mech2", None).role, Role.MECHANIC)

    def test_only_admin_actor_can_assign_roles(self):
        with self.assertRaises(PermissionDenied):
            make_user(self.svc, "xeng1", Role.ENGINEER, actor=self.mech)
        self.assertEqual(make_user(self.svc, "xadmin2", Role.ADMIN, actor=self.admin).role, Role.ADMIN)

    def test_registration_validation_and_duplicates(self):
        with self.assertRaises(ValidationError) as ctx:
            self.svc.auth.register(full_name="A", username="a b", email="bad", phone="12", password="x",
                                   confirm_password="y", role=Role.MECHANIC)
        self.assertGreaterEqual(len(ctx.exception.errors), 5)
        with self.assertRaises(ValidationError):
            make_user(self.svc, "MECH", Role.MECHANIC)  # username unique, case-insensitive

    def test_registration_can_be_closed(self):
        self.svc.settings.save(self.admin, {"registration_open": False})
        with self.assertRaises(PermissionDenied):
            make_user(self.svc, "late", Role.MECHANIC)
        self.assertEqual(make_user(self.svc, "late2", Role.GUEST, actor=self.admin).role, Role.GUEST)

    # --- login / sessions
    def test_login_by_username_or_email_logout_invalidates_session(self):
        for identifier in ("mech", "MECH@example.com"):
            session = self.svc.auth.login(identifier, GOOD)
            self.assertEqual(session.user.username, "mech")
            self.assertIsNotNone(self.svc.auth.validate(session.token))
            self.svc.auth.logout(session.token)
            self.assertIsNone(self.svc.auth.validate(session.token))

    def test_bad_credentials_generic_message(self):
        with self.assertRaises(AuthError) as a:
            self.svc.auth.login("mech", "Wrong!Pass1")
        with self.assertRaises(AuthError) as b:
            self.svc.auth.login("nobody", "Wrong!Pass1")
        self.assertEqual(str(a.exception), str(b.exception))

    def test_lockout_after_repeated_failures(self):
        for _ in range(5):
            with self.assertRaises(AuthError):
                self.svc.auth.login("mech", "Wrong!Pass1")
        with self.assertRaises(AuthError) as ctx:
            self.svc.auth.login("mech", GOOD)  # correct password still refused while locked
        self.assertIn("бұғатталды", str(ctx.exception))

    def test_remembered_session_resumes_and_disabled_user_cannot(self):
        session = self.svc.auth.login("mech", GOOD, remember=True)
        self.assertEqual(self.svc.auth.resume(session.token).user.id, self.mech.id)
        self.assertIsNone(self.svc.auth.resume("not-a-token"))
        self.svc.users.update(self.admin, self.mech.id, full_name="Mech Tester", email="mech@example.com",
                              phone="", role=Role.MECHANIC, is_active=False)
        self.assertIsNone(self.svc.auth.validate(session.token))
        with self.assertRaises(AuthError):
            self.svc.auth.login("mech", GOOD)

    def test_role_change_is_visible_in_validated_user(self):
        session = self.svc.auth.login("mech", GOOD)
        self.svc.users.update(self.admin, self.mech.id, full_name="Mech Tester", email="mech@example.com",
                              phone="", role=Role.ENGINEER, is_active=True)
        self.assertEqual(self.svc.auth.validate(session.token).role, Role.ENGINEER)

    def test_change_password_and_reset_code_flow(self):
        session = self.svc.auth.login("mech", GOOD)
        with self.assertRaises(ValidationError):
            self.svc.auth.change_password(session.user, "wrong", "N3w!Passw0rd", "N3w!Passw0rd")
        self.svc.auth.change_password(session.user, GOOD, "N3w!Passw0rd", "N3w!Passw0rd", token=session.token)
        self.svc.auth.login("mech", "N3w!Passw0rd")

        with self.assertRaises(PermissionDenied):
            self.svc.users.issue_reset_code(self.mech, self.guest.id)
        code = self.svc.users.issue_reset_code(self.admin, self.mech.id)
        with self.assertRaises(AuthError):
            self.svc.auth.reset_password("mech", "AAAA-AAAA", "R3set!Passw0rd", "R3set!Passw0rd")
        self.svc.auth.reset_password("mech@example.com", code.lower(), "R3set!Passw0rd", "R3set!Passw0rd")
        self.svc.auth.login("mech", "R3set!Passw0rd")
        with self.assertRaises(AuthError):  # code is single use
            self.svc.auth.reset_password("mech", code, "An0ther!Passw0rd", "An0ther!Passw0rd")

    def test_reset_code_locks_after_five_bad_guesses(self):
        code = self.svc.users.issue_reset_code(self.admin, self.mech.id)
        for _ in range(5):
            with self.assertRaises(AuthError):
                self.svc.auth.reset_password("mech", "ZZZZ-ZZZZ", "R3set!Passw0rd", "R3set!Passw0rd")
        with self.assertRaises(AuthError):
            self.svc.auth.reset_password("mech", code, "R3set!Passw0rd", "R3set!Passw0rd")

    # --- user administration
    def test_user_admin_rules(self):
        with self.assertRaises(PermissionDenied):
            self.svc.users.list(self.mech)
        with self.assertRaises(ValidationError):  # cannot delete self / last admin
            self.svc.users.delete(self.admin, self.admin.id)
        with self.assertRaises(ValidationError):
            self.svc.users.update(self.admin, self.admin.id, full_name="Boss Tester", email="boss@example.com",
                                  phone="", role=Role.MECHANIC, is_active=True)
        self.svc.users.delete(self.admin, self.guest.id)
        self.assertEqual(len(self.svc.users.list(self.admin)), 3)

    # --- permissions matrix
    def test_permission_matrix(self):
        self.assertTrue(role_can(Role.ADMIN, Perm.USERS_MANAGE))
        for role in (Role.MECHANIC, Role.ENGINEER, Role.GUEST):
            self.assertFalse(role_can(role, Perm.USERS_MANAGE))
            self.assertFalse(role_can(role, Perm.SYSTEM_SETTINGS))
        self.assertFalse(role_can(Role.MECHANIC, Perm.DIAG_ADVANCED))
        self.assertTrue(role_can(Role.ENGINEER, Perm.DIAG_ADVANCED))
        self.assertTrue(role_can(Role.ENGINEER, Perm.REPORT_TECHNICAL))
        self.assertFalse(role_can(Role.GUEST, Perm.DIAG_RUN))
        self.assertFalse(role_can(Role.GUEST, Perm.REPORT_SAVE))
        self.assertFalse(role_can(Role.GUEST, Perm.HISTORY_EDIT))

    # --- diagnostics + history
    def test_evaluate_states(self):
        profile = diagnostics.PROFILES["motor"]
        defaults = {s.key: s.default for s in profile.specs()}
        self.assertEqual(diagnostics.evaluate(profile, defaults).status, "success")
        slight = dict(defaults, vibration=2.1)       # 5% of span above the range
        self.assertEqual(diagnostics.evaluate(profile, slight).status, "warning")
        bad = dict(defaults, vibration=3.0, temperature=95)
        outcome = diagnostics.evaluate(profile, bad)
        self.assertEqual(outcome.status, "failed")
        self.assertLess(outcome.health, 60)
        with self.assertRaises(ValueError):
            diagnostics.evaluate(profile, dict(defaults, vibration=float("nan")))

    def _equipment_id(self, code="M-4000"):
        return next(e.id for e in self.svc.equipment.list() if e.code == code)

    def _values(self, advanced=False):
        return {s.key: s.default for s in diagnostics.PROFILES["motor"].specs(advanced)}

    def test_mechanic_runs_saves_and_sees_only_own_history(self):
        eq = self._equipment_id()
        record = self.svc.history.save_test(self.mech, eq, self._values())
        self.assertEqual((record.status, record.user_id), ("success", self.mech.id))
        self.assertRegex(record.test_code, r"^SD-\d{4}$")
        self.assertEqual([r.id for r in self.svc.history.search(self.mech)], [record.id])
        self.assertEqual(self.svc.history.search(self.eng), [])
        self.assertIn(record.id, [r.id for r in self.svc.history.search(self.admin)])
        with self.assertRaises(NotFound):
            self.svc.history.get(self.eng, record.id)

    def test_guest_sees_demo_only_and_cannot_write(self):
        records = self.svc.history.search(self.guest)
        self.assertEqual(sorted(r.test_code for r in records), ["SD-0246", "SD-0247", "SD-0248"])
        self.assertTrue(all(r.is_demo for r in records))
        eq = self._equipment_id()
        with self.assertRaises(PermissionDenied):
            self.svc.history.save_test(self.guest, eq, self._values())
        with self.assertRaises(PermissionDenied):
            self.svc.history.evaluate(self.guest, eq, self._values())
        with self.assertRaises(PermissionDenied):
            self.svc.history.register_check(self.guest, device="X", model="Y", category="Электр құралдары")
        with self.assertRaises(PermissionDenied):
            self.svc.history.delete(self.guest, records[0].id)
        with self.assertRaises(PermissionDenied):
            self.svc.history.update(self.guest, records[0].id, notes="hack")

    def test_cannot_touch_other_users_records(self):
        record = self.svc.history.save_test(self.mech, self._equipment_id(), self._values())
        with self.assertRaises(NotFound):
            self.svc.history.delete(self.eng, record.id)
        with self.assertRaises(NotFound):
            self.svc.history.update(self.eng, record.id, notes="x")
        self.svc.history.update(self.mech, record.id, notes="checked")
        self.assertEqual(self.svc.history.get(self.mech, record.id).notes, "checked")
        self.svc.history.delete(self.admin, record.id)
        with self.assertRaises(NotFound):
            self.svc.history.get(self.mech, record.id)

    def test_advanced_mode_needs_engineer(self):
        eq = self._equipment_id()
        with self.assertRaises(PermissionDenied):
            self.svc.history.save_test(self.mech, eq, self._values(True), advanced=True)
        record = self.svc.history.save_test(self.eng, eq, self._values(True), advanced=True, margin=0.2)
        self.assertIn("insulation", record.parameters)
        self.assertTrue(record.details["advanced"])
        trend = self.svc.history.trend(self.eng, eq)
        self.assertEqual([r.id for r in trend], [record.id])
        with self.assertRaises(PermissionDenied):
            self.svc.history.trend(self.mech, eq)

    def test_missing_parameter_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.svc.history.save_test(self.mech, self._equipment_id(), {"temperature": 40})

    def test_register_check_creates_equipment_and_pending_record(self):
        record = self.svc.history.register_check(
            self.mech, device="Bosch X", model="Drill", category="Электр құралдары", code="DRL-1")
        self.assertEqual((record.status, record.equipment_code), ("pending", "DRL-1"))
        with self.assertRaises(ValidationError):  # duplicate ID is rejected like the original form did
            self.svc.history.register_check(self.mech, device="b", model="c", category="Электр құралдары", code="drl-1")
        with self.assertRaises(ValidationError):
            self.svc.history.register_check(self.mech, device="", model="c", category="Электр құралдары")
        auto = self.svc.history.register_check(self.mech, device="Auto", model="ID", category="Тұрмыстық техника")
        self.assertTrue(auto.equipment_code.startswith("EQ-"))

    def test_equipment_rename_only_by_creator_or_admin(self):
        record = self.svc.history.register_check(self.mech, device="Mine", model="M1", category="Электр құралдары")
        self.svc.history.update(self.mech, record.id, notes="", name="Mine v2", model="M2")
        self.assertEqual(self.svc.history.get(self.mech, record.id).equipment_name, "Mine v2")
        seeded = self.svc.history.save_test(self.mech, self._equipment_id(), self._values())
        with self.assertRaises(PermissionDenied):
            self.svc.history.update(self.mech, seeded.id, notes="", name="Renamed", model="X")

    def test_filters_and_search(self):
        eq = self._equipment_id()
        bad = dict(self._values(), vibration=3.5, temperature=95)
        self.svc.history.save_test(self.mech, eq, self._values())
        self.svc.history.save_test(self.mech, eq, bad)
        failed = self.svc.history.search(self.mech, status="failed")
        self.assertEqual(len(failed), 1)
        self.assertEqual(len(self.svc.history.search(self.mech, text="M-40")), 2)
        self.assertEqual(self.svc.history.search(self.mech, text="100%_"), [])  # LIKE wildcards are escaped
        self.assertEqual(self.svc.history.counts(self.mech)["total"], 2)
        self.assertEqual(self.svc.history.counts(self.guest)["total"], 3)

    def test_stats_and_settings_admin_only(self):
        with self.assertRaises(PermissionDenied):
            self.svc.stats.system(self.eng)
        with self.assertRaises(PermissionDenied):
            self.svc.settings.save(self.mech, {"session_hours": 4})
        stats = self.svc.stats.system(self.admin)
        self.assertEqual(stats["users_total"], 4)
        self.assertEqual(stats["users_by_role"][Role.ADMIN], 1)
        with self.assertRaises(ValidationError):
            self.svc.settings.save(self.admin, {"session_hours": 9999})
        self.svc.settings.save(self.admin, {"session_hours": 4})
        self.assertEqual(self.svc.settings.get_all(self.admin)["session_hours"], "4")

    def test_deleting_user_keeps_reports_with_operator_name(self):
        record = self.svc.history.save_test(self.mech, self._equipment_id(), self._values())
        self.svc.users.delete(self.admin, self.mech.id)
        kept = self.svc.history.get(self.admin, record.id)
        self.assertIsNone(kept.user_id)
        self.assertEqual(kept.operator, "mech Tester")


if __name__ == "__main__":
    os.environ.setdefault("SMARTDIAGNOST_HOME", str(Path(__file__).parent / ".tmp"))
    unittest.main()
