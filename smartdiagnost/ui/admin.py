"""Administrator pages: user management and system statistics/settings."""
from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QHeaderView, QLabel, QLineEdit, QScrollArea, QSpinBox, QTableWidget,
    QTableWidgetItem, QWidget,
)

from desktop_visuals import column, label, row

from ..errors import SmartDiagnostError
from ..permissions import ROLE_LABELS, Perm, Role
from .auth_windows import StrengthMeter, format_errors, labeled, text_field
from .common import (
    STATUS_COLORS, StatCard, action_button, confirm, fmt_local, make_panel, page_header, show_error, show_info,
)


class UserEditDialog(QDialog):
    """Create (user is None) or edit an account. Any role can be assigned here, subject to administrator rights."""

    def __init__(self, ctx, user=None, parent=None):
        super().__init__(parent)
        self.ctx, self.user = ctx, user
        self.setObjectName("authDialog")
        self.setWindowTitle("Пайдаланушыны өңдеу" if user else "Жаңа пайдаланушы")
        self.setMinimumWidth(500)
        layout = column(self, (28, 24, 28, 22), 8)
        layout.addWidget(label("Пайдаланушыны өңдеу" if user else "Жаңа пайдаланушы", "authTitle"))
        self.full_name = text_field("user", "Аты-жөні")
        self.username = text_field("user", "Пайдаланушы аты")
        self.email = text_field("mail", "name@example.com")
        self.phone = text_field("phone", "+7 700 000 00 00")
        self.password = text_field("lock", "Құпиясөз" if not user else "Жаңа құпиясөз (міндетті емес)", password=True)
        self.role = QComboBox()
        self.role.setMinimumHeight(40)
        self.role.setAccessibleName("Рөл")
        for role in Role:
            self.role.addItem(ROLE_LABELS[role], role)
        self.active = QCheckBox("Тіркелгі белсенді")
        self.active.setChecked(True)
        labeled(layout, "Толық аты-жөні", self.full_name)
        pair = row(spacing=12)
        for caption, widget in (("Пайдаланушы аты", self.username), ("Телефон", self.phone)):
            cell = column(spacing=4)
            labeled(cell, caption, widget)
            pair.addLayout(cell, 1)
        layout.addLayout(pair)
        labeled(layout, "Email", self.email)
        labeled(layout, "Құпиясөз" if not user else "Жаңа құпиясөз", self.password)
        self.meter = StrengthMeter()
        layout.addWidget(self.meter)
        labeled(layout, "Рөл", self.role)
        layout.addWidget(self.active)
        if user:
            self.full_name.setText(user.full_name)
            self.username.setText(user.username)
            self.username.setEnabled(False)
            self.email.setText(user.email)
            self.phone.setText(user.phone)
            self.role.setCurrentIndex(self.role.findData(user.role))
            self.active.setChecked(user.is_active)
            self.active.setEnabled(user.id != ctx.user.id)
            if user.id == ctx.user.id:
                layout.addWidget(label("Өз тіркелгіңізді өшіру мүмкін емес.", "micro"))
        self.password.textChanged.connect(
            lambda: self.meter.update_for(self.password.text(), self.username.text(), self.email.text()))
        self.error = label("", "error", wrap=True)
        self.error.hide()
        layout.addWidget(self.error)
        buttons = row(spacing=8)
        cancel = action_button("Бас тарту", "outline", 40)
        cancel.clicked.connect(self.reject)
        save = action_button("Сақтау", "primary", 40)
        save.setDefault(True)
        save.clicked.connect(self.save)
        buttons.addWidget(cancel)
        buttons.addWidget(save, 1)
        layout.addSpacing(4)
        layout.addLayout(buttons)

    def save(self):
        users = self.ctx.services.users
        try:
            if self.user is None:
                users.create(
                    self.ctx.user, full_name=self.full_name.text(), username=self.username.text(),
                    email=self.email.text(), phone=self.phone.text(), password=self.password.text(),
                    role=self.role.currentData())
            else:
                users.update(
                    self.ctx.user, self.user.id, full_name=self.full_name.text(), email=self.email.text(),
                    phone=self.phone.text(), role=self.role.currentData(), is_active=self.active.isChecked(),
                    new_password=self.password.text() or None)
        except SmartDiagnostError as error:
            self.error.setText(format_errors(error))
            self.error.show()
            return
        self.accept()


class ResetCodeDialog(QDialog):
    def __init__(self, user, code, parent=None):
        super().__init__(parent)
        self.setObjectName("authDialog")
        self.setWindowTitle("Қалпына келтіру коды")
        self.setMinimumWidth(420)
        layout = column(self, (28, 24, 28, 22), 10)
        layout.addWidget(label("Қалпына келтіру коды", "authTitle"))
        layout.addWidget(label(
            f"«{user.username}» пайдаланушысына бір реттік код жасалды. Кодты пайдаланушыға қауіпсіз түрде беріңіз. "
            "Код 30 минут жарамды; оны енгізгеннен кейін пайдаланушы жаңа құпиясөз таңдайды.", "muted", wrap=True))
        code_label = label(code, "resetCode")
        code_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(code_label)
        layout.addWidget(label("Бұл код қайта көрсетілмейді.", "micro"))
        buttons = row(spacing=8)
        copy = action_button("Көшіру", "outline", 40)
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(code))
        close = action_button("Жабу", "primary", 40)
        close.clicked.connect(self.accept)
        buttons.addWidget(copy)
        buttons.addWidget(close, 1)
        layout.addLayout(buttons)


class UsersPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.users = []
        self.timer = QTimer(self, singleShot=True, interval=200)
        self.timer.timeout.connect(self.refresh)
        outer = column(self, (24, 20, 24, 17), 14)
        outer.addWidget(page_header("Пайдаланушылар", "Тіркелгілерді құру, өңдеу, рөл тағайындау және жою."))
        panel, body = make_panel("Тіркелгілер", "", "USERS", height=66)
        self.count = panel.findChild(QLabel, "muted")
        outer.addWidget(panel, 1)

        tools = row(margins=(16, 12, 16, 8), spacing=8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Аты, username немесе email іздеу…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(38)
        self.search.textChanged.connect(lambda: self.timer.start())
        self.role_filter = QComboBox()
        self.role_filter.addItem("Барлық рөл", None)
        for role in Role:
            self.role_filter.addItem(ROLE_LABELS[role], role)
        self.role_filter.currentIndexChanged.connect(self.refresh)
        new = action_button("+  Жаңа пайдаланушы", "primary", 38)
        new.clicked.connect(self.create)
        self.edit_button = action_button("Өңдеу", "outline", 38)
        self.edit_button.clicked.connect(self.edit)
        self.reset_button = action_button("Қалпына келтіру коды", "outline", 38)
        self.reset_button.clicked.connect(self.issue_code)
        self.delete_button = action_button("Жою", "outline", 38)
        self.delete_button.clicked.connect(self.delete)
        for widget in (self.search,):
            tools.addWidget(widget, 1)
        for widget in (self.role_filter, new, self.edit_button, self.reset_button, self.delete_button):
            tools.addWidget(widget)
        body.addLayout(tools)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["АТЫ-ЖӨНІ", "USERNAME", "EMAIL / ТЕЛЕФОН", "РӨЛ", "КҮЙ", "СОҢҒЫ КІРУ"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(260)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.update_buttons)
        self.table.doubleClicked.connect(lambda *_: self.edit())
        body.addWidget(self.table, 1)
        ctx.users_changed.connect(self.refresh)
        self.update_buttons()
        self.refresh()

    def on_show(self):
        self.refresh()

    def selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self.users[rows[0].row()] if rows and rows[0].row() < len(self.users) else None

    def update_buttons(self):
        has = self.selected() is not None
        for button in (self.edit_button, self.reset_button, self.delete_button):
            button.setEnabled(has)

    def refresh(self):
        keep = self.selected().id if self.selected() else None
        try:
            self.users = self.ctx.services.users.list(self.ctx.user, self.search.text(), self.role_filter.currentData())
        except SmartDiagnostError as error:
            show_error(self, error)
            return
        self.count.setText(f"{len(self.users)} пайдаланушы")
        with QSignalBlocker(self.table):
            self.table.setRowCount(len(self.users))
            for index, user in enumerate(self.users):
                last = fmt_local(user.last_login_at, "dd.MM.yyyy HH:mm") if user.last_login_at else "—"
                state = "● Белсенді" if user.is_active else "○ Өшірілген"
                cells = (user.full_name, user.username, f"{user.email}\n{user.phone or '—'}", user.role_label, state, last)
                for col, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    item.setToolTip(text)
                    if col == 4:
                        item.setForeground(QColor(STATUS_COLORS["success"] if user.is_active else "#829bb3"))
                    self.table.setItem(index, col, item)
                if user.id == keep:
                    self.table.selectRow(index)
        self.update_buttons()

    def _changed(self):
        self.ctx.users_changed.emit()
        self.ctx.history_changed.emit()

    def create(self):
        if UserEditDialog(self.ctx, None, self).exec() == QDialog.DialogCode.Accepted:
            self._changed()

    def edit(self):
        user = self.selected()
        if user and UserEditDialog(self.ctx, user, self).exec() == QDialog.DialogCode.Accepted:
            self._changed()

    def issue_code(self):
        user = self.selected()
        if not user:
            return
        try:
            code = self.ctx.services.users.issue_reset_code(self.ctx.user, user.id)
        except SmartDiagnostError as error:
            show_error(self, error)
            return
        ResetCodeDialog(user, code, self).exec()

    def delete(self):
        user = self.selected()
        if not user:
            return
        if not confirm(self, f"«{user.username}» тіркелгісін жою керек пе?\nОның диагностика есептері сақталады.", "Жою"):
            return
        try:
            self.ctx.services.users.delete(self.ctx.user, user.id)
        except SmartDiagnostError as error:
            show_error(self, error)
            return
        self._changed()


class SystemPage(QWidget):
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
        layout.addWidget(page_header("Жүйе", "Жүйе статистикасы және қауіпсіздік параметрлері."))

        cards = row(spacing=14)
        self.cards = {
            "users": StatCard("Пайдаланушылар", "#4fd8ee"),
            "tests": StatCard("Барлық тесттер", "#4c9bfa"),
            "week": StatCard("Соңғы 7 күн", "#4c9bfa"),
            "rate": StatCard("Сәттілік көрсеткіші", STATUS_COLORS["success"]),
        }
        for card in self.cards.values():
            cards.addWidget(card, 1)
        layout.addLayout(cards)

        middle = row(spacing=16)
        roles_panel, roles_body = make_panel("Рөлдер және белсенділік", None, "STATS", height=66)
        self.rows = column(margins=(18, 12, 18, 16), spacing=8)
        roles_body.addLayout(self.rows)
        middle.addWidget(roles_panel, 1, Qt.AlignmentFlag.AlignTop)

        settings_panel, settings_body = make_panel("Жүйе баптаулары", "SECURITY & SESSIONS", ctx=ctx, technical=True,
                                                   height=66)
        form = column(margins=(18, 14, 18, 16), spacing=10)
        self.registration = QCheckBox("Өз бетінше тіркелуге рұқсат (Механик / Қонақ)")
        form.addWidget(self.registration)
        self.spins = {}
        for key, caption, low, high, suffix in (
            ("session_hours", "Сессия ұзақтығы", 1, 72, " сағ"),
            ("remember_days", "«Мені есте сақта» ұзақтығы", 1, 90, " күн"),
            ("max_failed_attempts", "Қате кіру әрекеттері (бұғаттау алдында)", 3, 10, ""),
            ("lockout_minutes", "Бұғаттау уақыты", 1, 60, " мин"),
        ):
            spin = QSpinBox()
            spin.setRange(low, high)
            spin.setSuffix(suffix)
            spin.setAccessibleName(caption)
            self.spins[key] = spin
            line = row(spacing=10)
            line.addWidget(label(caption, "muted"), 1)
            line.addWidget(spin)
            form.addLayout(line)
        save = action_button("Баптауларды сақтау", "primary", 40)
        save.clicked.connect(self.save)
        form.addWidget(save)
        settings_body.addLayout(form)
        middle.addWidget(settings_panel, 1, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(middle)
        layout.addStretch()
        ctx.history_changed.connect(self.refresh)
        ctx.users_changed.connect(self.refresh)
        self.refresh()

    def on_show(self):
        self.refresh()

    def refresh(self):
        stats = self.ctx.services.stats.system(self.ctx.user)
        self.cards["users"].set(stats["users_total"], f"белсенді: {stats['users_active']}")
        self.cards["tests"].set(stats["tests_total"], f"сәтсіз: {stats['counts']['failed']}")
        self.cards["week"].set(stats["tests_week"], "жаңа диагностика")
        self.cards["rate"].set(f"{stats['success_rate']}%" if stats["success_rate"] is not None else "—",
                               "аяқталған тесттерден")
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        entries = [(f"Рөл · {ROLE_LABELS[role]}", str(count)) for role, count in stats["users_by_role"].items()]
        entries.append(("", ""))
        entries += [(f"Белсенді орындаушы · {name}", f"{count} тест") for name, count in stats["top_operators"]] or [
            ("Орындаушылар белсенділігі жоқ", "")]
        for caption, value in entries:
            holder = QWidget()
            line = row(holder, spacing=8)
            line.addWidget(label(caption, "muted"))
            line.addStretch()
            line.addWidget(label(value, ""))
            self.rows.addWidget(holder)
        values = self.ctx.services.settings.get_all(self.ctx.user)
        self.registration.setChecked(values["registration_open"] == "1")
        for key, spin in self.spins.items():
            spin.setValue(int(values[key]))

    def save(self):
        values = {key: spin.value() for key, spin in self.spins.items()}
        values["registration_open"] = self.registration.isChecked()
        try:
            self.ctx.services.settings.save(self.ctx.user, values)
        except SmartDiagnostError as error:
            show_error(self, error)
            return
        show_info(self, "Баптаулар сақталды. Жаңа мәндер келесі кірулерге қолданылады.")
