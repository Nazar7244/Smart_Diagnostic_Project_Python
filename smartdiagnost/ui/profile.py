"""User profile: personal data, password change and session control."""
from PySide6.QtWidgets import QLineEdit, QScrollArea, QWidget

from desktop_visuals import column, label, row

from ..errors import SmartDiagnostError
from ..permissions import Role
from .auth_windows import StrengthMeter, labeled, text_field
from .common import action_button, confirm, fmt_local, make_panel, page_header, role_badge, show_error, show_info


class ProfilePage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        outer = column(self)
        scroll = QScrollArea(widgetResizable=True)
        outer.addWidget(scroll)
        surface = QWidget()
        surface.setObjectName("surface")
        scroll.setWidget(surface)
        layout = column(surface, (24, 20, 24, 20), 16)
        layout.addWidget(page_header("Профиль", "Жеке деректеріңіз бен қауіпсіздік параметрлері."))
        columns = row(spacing=16)
        layout.addLayout(columns)

        info_panel, info_body = make_panel("Жеке деректер", "PERSONAL DETAILS", ctx=ctx, technical=True, height=66)
        form = column(margins=(18, 14, 18, 18), spacing=8)
        self.role_chip = role_badge("", "guest")
        top = row(spacing=10)
        top.addWidget(label("Рөл", "muted"))
        top.addWidget(self.role_chip)
        top.addStretch()
        form.addLayout(top)
        self.full_name = QLineEdit()
        self.username = QLineEdit()
        self.username.setEnabled(False)
        self.email = QLineEdit()
        self.phone = QLineEdit()
        for caption, widget in (("Толық аты-жөні", self.full_name), ("Пайдаланушы аты", self.username),
                                ("Email", self.email), ("Телефон", self.phone)):
            labeled(form, caption, widget)
            widget.setMinimumHeight(40)
        self.dates = label("", "micro", wrap=True)
        form.addWidget(self.dates)
        self.save_button = action_button("Өзгерістерді сақтау", "primary", 40)
        self.save_button.clicked.connect(self.save_profile)
        form.addWidget(self.save_button)
        self.guest_note = label("Қонақ тіркелгісінің деректерін өзгертуге болмайды.", "micro", wrap=True)
        form.addWidget(self.guest_note)
        info_body.addLayout(form)
        columns.addWidget(info_panel, 1)

        security_panel, security_body = make_panel("Қауіпсіздік", "PASSWORD & SESSIONS", ctx=ctx, technical=True,
                                                   height=66)
        sec = column(margins=(18, 14, 18, 18), spacing=8)
        self.current = text_field("lock", "Ағымдағы құпиясөз", password=True)
        self.new = text_field("lock", "Жаңа құпиясөз", password=True)
        self.confirm_new = text_field("lock", "Жаңа құпиясөзді қайталаңыз", password=True)
        labeled(sec, "Ағымдағы құпиясөз", self.current)
        labeled(sec, "Жаңа құпиясөз", self.new)
        self.meter = StrengthMeter()
        sec.addWidget(self.meter)
        labeled(sec, "Құпиясөзді растау", self.confirm_new)
        self.new.textChanged.connect(lambda: self.meter.update_for(
            self.new.text(), self.ctx.user.username, self.ctx.user.email, self.ctx.user.full_name))
        change = action_button("Құпиясөзді өзгерту", "primary", 40)
        change.clicked.connect(self.change_password)
        sec.addWidget(change)
        sec.addSpacing(8)
        self.sessions = label("", "muted", wrap=True)
        sec.addWidget(self.sessions)
        others = action_button("Басқа сессиялардан шығу", "outline", 38)
        others.clicked.connect(self.logout_others)
        sec.addWidget(others)
        security_body.addLayout(sec)
        columns.addWidget(security_panel, 1)
        layout.addStretch()
        ctx.user_updated.connect(self.load)
        self.load()

    def on_show(self):
        self.load()

    def load(self):
        user = self.ctx.user
        self.role_chip.setText(user.role_label.upper())
        self.role_chip.setProperty("role", user.role.value)
        self.role_chip.style().unpolish(self.role_chip)
        self.role_chip.style().polish(self.role_chip)
        self.full_name.setText(user.full_name)
        self.username.setText(user.username)
        self.email.setText(user.email)
        self.phone.setText(user.phone)
        last = fmt_local(user.last_login_at) if user.last_login_at else "—"
        self.dates.setText(f"Тіркелген күні: {fmt_local(user.created_at, 'dd.MM.yyyy')}  ·  Соңғы кіру: {last}")
        guest = user.role is Role.GUEST
        for widget in (self.full_name, self.email, self.phone, self.save_button):
            widget.setEnabled(not guest)
        self.guest_note.setVisible(guest)
        count = self.ctx.services.auth.active_session_count(user)
        self.sessions.setText(f"Белсенді сессиялар: {count}")

    def save_profile(self):
        try:
            updated = self.ctx.services.auth.update_profile(
                self.ctx.user, full_name=self.full_name.text(), email=self.email.text(), phone=self.phone.text())
        except SmartDiagnostError as error:
            show_error(self, error)
            return
        self.ctx.update_user(updated)
        show_info(self, "Профиль жаңартылды.")

    def change_password(self):
        try:
            self.ctx.services.auth.change_password(
                self.ctx.user, self.current.text(), self.new.text(), self.confirm_new.text(), self.ctx.token)
        except SmartDiagnostError as error:
            show_error(self, error)
            return
        for edit in (self.current, self.new, self.confirm_new):
            edit.clear()
        show_info(self, "Құпиясөз өзгертілді. Басқа сессиялар аяқталды.")
        self.load()

    def logout_others(self):
        if confirm(self, "Басқа құрылғылардағы барлық сессияларды аяқтау керек пе?", "Шығу"):
            self.ctx.services.auth.logout_other_sessions(self.ctx.user, self.ctx.token)
            self.load()
