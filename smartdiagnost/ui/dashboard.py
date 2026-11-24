"""Personalised dashboard: welcome, live clock, KPI tiles, recent activity and quick access to modules."""
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QScrollArea, QWidget

from desktop_visuals import column, frame, icon, label, row

from ..errors import SmartDiagnostError
from ..models import STATUS_LABELS
from ..permissions import Perm, Role
from .common import (
    STATUS_COLORS, STATUS_GLYPHS, StatCard, StatusBar, fmt_local, make_panel, role_badge, show_error, status_badge,
)
from .history import RecordDialog

WEEKDAYS = ("Дүйсенбі", "Сейсенбі", "Сәрсенбі", "Бейсенбі", "Жұма", "Сенбі", "Жексенбі")
MONTHS = ("қаңтар", "ақпан", "наурыз", "сәуір", "мамыр", "маусым", "шілде", "тамыз", "қыркүйек", "қазан", "қараша",
          "желтоқсан")

SCOPE_TEXT = {
    Role.ADMIN: "Жүйе бойынша жалпы статистика",
    Role.MECHANIC: "Сіздің жеке диагностика статистикаңыз",
    Role.ENGINEER: "Сіздің жеке диагностика статистикаңыз",
    Role.GUEST: "Демо режим · үлгі нәтижелер, тек көру",
}


class ActivityRow(QFrame):
    clicked = Signal()

    def __init__(self, record, show_operator):
        super().__init__()
        self.setObjectName("activityRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Есепті ашу")
        layout = row(self, (14, 9, 14, 9), 12)
        glyph = label(STATUS_GLYPHS[record.status], "")
        glyph.setFixedWidth(18)
        glyph.setStyleSheet(f"color:{STATUS_COLORS[record.status]};font-size:15px;font-weight:700;")
        layout.addWidget(glyph)
        texts = column(spacing=2)
        title = label(f"{record.equipment_name} · {record.equipment_model}".strip(" ·"), "")
        title.setTextFormat(Qt.TextFormat.PlainText)
        meta = f"{record.test_code}" + (f" · {record.operator}" if show_operator else "")
        subtitle = label(meta, "muted")
        subtitle.setTextFormat(Qt.TextFormat.PlainText)
        texts.addWidget(title)
        texts.addWidget(subtitle)
        layout.addLayout(texts, 1)
        layout.addWidget(label(fmt_local(record.performed_at, "dd.MM.yyyy HH:mm"), "muted"))
        layout.addWidget(status_badge(record.status))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class DashboardPage(QWidget):
    def __init__(self, ctx, modules, navigate):
        super().__init__()
        self.ctx, self.navigate = ctx, navigate
        outer = column(self)
        scroll = QScrollArea(widgetResizable=True)
        outer.addWidget(scroll)
        surface = QWidget()
        surface.setObjectName("surface")
        scroll.setWidget(surface)
        layout = column(surface, (24, 20, 24, 20), 16)

        top = row(spacing=16)
        greeting = column(spacing=6)
        self.welcome = label("", "welcome")
        self.welcome.setTextFormat(Qt.TextFormat.PlainText)
        meta = row(spacing=10)
        self.role_chip = role_badge("", "guest")
        meta.addWidget(self.role_chip)
        meta.addWidget(label(SCOPE_TEXT[ctx.user.role], "muted"))
        meta.addStretch()
        greeting.addWidget(self.welcome)
        greeting.addLayout(meta)
        top.addLayout(greeting, 1)
        clock = column(spacing=2)
        self.time = label("", "clock")
        self.date = label("", "muted")
        self.time.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.date.setAlignment(Qt.AlignmentFlag.AlignRight)
        clock.addWidget(self.time)
        clock.addWidget(self.date)
        top.addLayout(clock)
        layout.addLayout(top)

        cards = row(spacing=14)
        self.total = StatCard("Барлық тесттер", "#4fd8ee")
        self.success = StatCard("Сәтті тесттер", STATUS_COLORS["success"])
        self.failed = StatCard("Сәтсіз тесттер", STATUS_COLORS["failed"])
        self.warning = StatCard("Ескертулер", STATUS_COLORS["warning"])
        for card in (self.total, self.success, self.failed, self.warning):
            cards.addWidget(card, 1)
        layout.addLayout(cards)

        middle = row(spacing=16)
        self.activity_panel, activity_body = make_panel("Соңғы белсенділік", "", "RECENT", height=66)
        self.activity_hint = self.activity_panel.findChild(QLabel, "muted")
        holder = column(margins=(18, 14, 18, 16), spacing=10)
        self.status_bar = StatusBar()
        holder.addWidget(self.status_bar)
        self.activity_rows = column(spacing=6)
        holder.addLayout(self.activity_rows)
        self.empty = label("Әзірге диагностика жоқ. Жабдық диагностикасынан тест іске қосыңыз.", "muted", wrap=True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setMinimumHeight(70)
        holder.addWidget(self.empty)
        holder.addStretch()
        activity_body.addLayout(holder)
        middle.addWidget(self.activity_panel, 3, Qt.AlignmentFlag.AlignTop)

        side = column(spacing=16)
        quick_panel, quick_body = make_panel("Тез қол жеткізу", None, "MODULES", height=66)
        grid = QGridLayout()
        grid.setContentsMargins(16, 14, 16, 16)
        grid.setSpacing(10)
        for index, (key, title, description, icon_name) in enumerate(modules):
            button = QPushButton(f"  {title}\n  {description}")
            button.setObjectName("module")
            button.setIcon(icon(icon_name, "#4fd8ee"))
            button.setIconSize(QSize(22, 22))
            button.setMinimumHeight(64)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, target=key: self.navigate(target))
            grid.addWidget(button, index // 2, index % 2)
        quick_body.addLayout(grid)
        side.addWidget(quick_panel)

        self.system_panel = None
        if ctx.can(Perm.SYSTEM_STATS):
            self.system_panel, system_body = make_panel("Жүйе статистикасы", None, "ADMIN", height=66)
            self.system_rows = column(margins=(18, 12, 18, 16), spacing=8)
            system_body.addLayout(self.system_rows)
            side.addWidget(self.system_panel)
        side.addStretch()
        middle.addLayout(side, 2)
        layout.addLayout(middle)
        layout.addStretch()

        self.clock_timer = QTimer(self, interval=1000)
        self.clock_timer.timeout.connect(self.tick)
        self.clock_timer.start()
        ctx.history_changed.connect(self.refresh)
        ctx.users_changed.connect(self.refresh)
        ctx.user_updated.connect(self.refresh)
        self.tick()
        self.refresh()

    def tick(self):
        now = datetime.now()
        self.time.setText(now.strftime("%H:%M:%S"))
        self.date.setText(f"{WEEKDAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]} {now.year}")

    def on_show(self):
        self.refresh()

    def refresh(self):
        user = self.ctx.user
        self.welcome.setText(f"Қош келдіңіз, {user.full_name}!")
        self.role_chip.setText(user.role_label.upper())
        self.role_chip.setProperty("role", user.role.value)
        self.role_chip.style().unpolish(self.role_chip)
        self.role_chip.style().polish(self.role_chip)
        history = self.ctx.services.history
        try:
            counts = history.counts(user)
            recent = history.search(user, limit=6)
        except SmartDiagnostError as error:
            show_error(self, error)
            return
        total = counts["total"]
        percent = lambda n: f"{round(100 * n / total)}% барлық тесттен" if total else "Деректер жоқ"  # noqa: E731
        self.total.set(total, "Жүйе бойынша" if user.can(Perm.HISTORY_ALL) else "Менің тесттерім" if user.can(
            Perm.HISTORY_OWN) else "Үлгі нәтижелер")
        self.success.set(counts["success"], percent(counts["success"]))
        self.failed.set(counts["failed"], percent(counts["failed"]))
        self.warning.set(counts["warning"], f"{counts['pending']} күтілуде")
        self.status_bar.set_counts(counts)
        self.activity_hint.setText(f"Соңғы {len(recent)} жазба")

        while self.activity_rows.count():
            item = self.activity_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        show_operator = user.can(Perm.HISTORY_ALL)
        for record in recent:
            row_widget = ActivityRow(record, show_operator)
            row_widget.clicked.connect(lambda rec=record: RecordDialog(self.ctx, rec, self).exec())
            self.activity_rows.addWidget(row_widget)
        self.empty.setVisible(not recent)
        if self.system_panel is not None:
            self.refresh_system()

    def refresh_system(self):
        stats = self.ctx.services.stats.system(self.ctx.user)
        while self.system_rows.count():
            item = self.system_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        lines = [
            ("Пайдаланушылар", f"{stats['users_total']}  ·  белсенді {stats['users_active']}"),
            *((f"   {ROLE_TITLES[role]}", str(count)) for role, count in stats["users_by_role"].items()),
            ("Соңғы 7 күндегі тесттер", str(stats["tests_week"])),
            ("Сәттілік көрсеткіші", f"{stats['success_rate']}%" if stats["success_rate"] is not None else "—"),
        ]
        for caption, value in lines:
            line = row(spacing=8)
            line.addWidget(label(caption, "muted"))
            line.addStretch()
            line.addWidget(label(value, ""))
            holder = QWidget()
            holder.setLayout(line)
            self.system_rows.addWidget(holder)


ROLE_TITLES = {Role.ADMIN: "Әкімшілер", Role.ENGINEER: "Инженерлер", Role.MECHANIC: "Механиктер", Role.GUEST: "Қонақтар"}
