"""Main application window: role-aware sidebar, topbar and the stack of pages."""
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QButtonGroup, QLineEdit, QMainWindow, QMenu, QPushButton, QScrollArea, QStackedWidget, QToolButton, QWidget,
)

from desktop_visuals import PUBLIC, column, frame, icon, label, row

from ..config import APP_NAME, APP_VERSION
from ..permissions import Perm
from .admin import SystemPage, UsersPage
from .common import action_button, centered_badge, confirm, fade_in, fmt_local, progress, role_badge, show_info
from .context import AppContext
from .dashboard import DashboardPage
from .history import HistoryPage
from .lab import LabPage
from .profile import ProfilePage
from .workspace import DiagnosticWorkspace

SESSION_CHECK_MS = 30_000


@dataclass(frozen=True)
class PageSpec:
    key: str
    title: str
    icon: str
    description: str
    allowed: callable
    quick: bool = True        # offered as a quick-access card on the dashboard
    group: str = "main"


PAGES = (
    PageSpec("dashboard", "Басқару панелі", "grid", "", lambda u: True, quick=False),
    PageSpec("engine", "Қозғалтқыш", "pulse", "Сандық егіз, датчиктер, ЖИ талдау",
             lambda u: u.can(Perm.DIAG_ENGINE) or u.can(Perm.DEMO_MODE)),
    PageSpec("equipment", "Жабдық", "wrench", "Жаңа тексеріс және диагностика тесті",
             lambda u: u.can(Perm.DIAG_EQUIPMENT)),
    PageSpec("lab", "Инженерлік зертхана", "flask", "Кеңейтілген талдау, тренд, техникалық есеп",
             lambda u: u.can(Perm.DIAG_ADVANCED)),
    PageSpec("history", "Тарих", "history", "Диагностика есептері, іздеу, экспорт",
             lambda u: u.can(Perm.HISTORY_OWN) or u.can(Perm.HISTORY_ALL) or u.can(Perm.HISTORY_DEMO)),
    PageSpec("users", "Пайдаланушылар", "users", "Тіркелгілер мен рөлдерді басқару",
             lambda u: u.can(Perm.USERS_MANAGE), group="admin"),
    PageSpec("system", "Жүйе", "shield", "Статистика және жүйе баптаулары",
             lambda u: u.can(Perm.SYSTEM_STATS), group="admin"),
    PageSpec("settings", "Баптаулар", "settings", "Тіл және сигнал көзі", lambda u: True, quick=False),
    PageSpec("profile", "Профиль", "user", "", lambda u: True, quick=False),
)


class MainWindow(QMainWindow):
    logout_requested = Signal()

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.ending = False
        self.nav_buttons = {}
        self.pages = {}
        self.specs = {spec.key: spec for spec in PAGES if spec.allowed(ctx.user)}
        self.setWindowTitle(f"{APP_NAME} · Industrial Titan")
        self.setWindowIcon(QIcon(str(PUBLIC / "favicon.png")))
        self.setMinimumSize(1100, 670)
        self.resize(1365, 900)

        workspace = QWidget()
        workspace.setObjectName("workspace")
        self.setCentralWidget(workspace)
        shell = row(workspace)
        shell.addWidget(self.build_sidebar())
        main = column()
        shell.addLayout(main, 1)
        main.addWidget(self.build_topbar())
        self.stack = QStackedWidget()
        main.addWidget(self.stack, 1)
        self.build_pages()

        self.guard = QTimer(self, interval=SESSION_CHECK_MS)
        self.guard.timeout.connect(self.check_session)
        self.guard.start()
        ctx.user_updated.connect(self.refresh_user)
        self.navigate("dashboard")

    # ------------------------------------------------------------------ construction
    def build_pages(self):
        ctx = self.ctx
        modules = [(s.key, s.title, s.description, s.icon) for s in self.specs.values() if s.quick]
        add = lambda key, page: (self.pages.__setitem__(key, page), self.stack.addWidget(page))  # noqa: E731
        add("dashboard", DashboardPage(ctx, modules, self.navigate))
        self.workspace = DiagnosticWorkspace(ctx)
        self.stack.addWidget(self.workspace)
        for key in ("engine", "equipment", "settings"):
            if key in self.specs:
                self.pages[key] = self.workspace
        if "lab" in self.specs:
            add("lab", LabPage(ctx))
        if "history" in self.specs:
            self.history = HistoryPage(ctx)
            add("history", self.history)
        if "users" in self.specs:
            add("users", UsersPage(ctx))
        if "system" in self.specs:
            add("system", SystemPage(ctx))
        add("profile", ProfilePage(ctx))

    def build_sidebar(self):
        sidebar = frame("sidebar")
        layout = column(sidebar, (13, 41, 15, 13), 0)
        brand = row(spacing=11)
        mark = frame("brandMark")
        mark.setFixedSize(38, 38)
        bars = row(mark, (10, 0, 10, 8), 3)
        for height in (9, 17, 12):
            bar = frame("brandBar")
            bar.setFixedSize(3, height)
            bars.addWidget(bar, 0, Qt.AlignmentFlag.AlignBottom)
        brand.addWidget(mark)
        names = column(spacing=3)
        names.addWidget(label('Smart<span style="color:#4c9bfa">Diagnost</span> <span style="color:#4fd8ee">PRO</span>',
                              "brandName"))
        names.addWidget(self.ctx.technical("I N D U S T R I A L   T I T A N"))
        brand.addLayout(names)
        brand.addStretch()
        layout.addLayout(brand)
        layout.addSpacing(40)
        layout.addWidget(label("Ж Ұ М Ы С   К Е Ң І С Т І Г І", "muted"))
        layout.addSpacing(12)

        self.nav_group = QButtonGroup(self)
        shown_admin_heading = False
        for spec in self.specs.values():
            if spec.key == "profile":
                continue
            if spec.group == "admin" and not shown_admin_heading:
                layout.addSpacing(10)
                layout.addWidget(label("Ә К І М Ш І", "muted"))
                layout.addSpacing(8)
                shown_admin_heading = True
            button = action_button(f"  {spec.title}", "nav", 46)
            button.setCheckable(True)
            button.setIcon(icon(spec.icon))
            button.setIconSize(QSize(19, 19))
            button.setToolTip(spec.description or spec.title)
            button.clicked.connect(lambda checked=False, key=spec.key: self.navigate(key))
            self.nav_group.addButton(button)
            self.nav_buttons[spec.key] = button
            layout.addWidget(button)
            layout.addSpacing(5)
        layout.addStretch()

        card = frame("userCard")
        card_layout = column(card, (12, 12, 12, 12), 10)
        person = row(spacing=10)
        self.avatar = centered_badge("", "avatar", 40)
        person.addWidget(self.avatar)
        self.user_button = QPushButton()
        self.user_button.setObjectName("userButton")
        self.user_button.setFlat(True)
        self.user_button.setToolTip("Профильді ашу")
        self.user_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.user_button.clicked.connect(lambda: self.navigate("profile"))
        person.addWidget(self.user_button, 1)
        logout = QToolButton()
        logout.setObjectName("logout")
        logout.setIcon(icon("logout", "#f2788a"))
        logout.setIconSize(QSize(18, 18))
        logout.setToolTip("Жүйеден шығу")
        logout.setAccessibleName("Жүйеден шығу")
        logout.setFixedSize(36, 36)
        logout.clicked.connect(self.request_logout)
        person.addWidget(logout)
        card_layout.addLayout(person)
        self.role_chip = role_badge("", "guest")
        card_layout.addWidget(self.role_chip)
        card_layout.addWidget(progress())
        card_layout.addWidget(label(f"Деректер SQLite базасында сақталады · v{APP_VERSION}", "micro", wrap=True))
        layout.addWidget(card)
        self.refresh_user()

        scroll = QScrollArea(widgetResizable=True)
        scroll.setFixedWidth(268)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(sidebar)
        return scroll

    def build_topbar(self):
        topbar = frame("topbar")
        topbar.setFixedHeight(80)
        layout = row(topbar, (24, 0, 20, 0), 12)
        layout.addWidget(label("SmartDiagnost  /", "muted"))
        self.breadcrumb = label("")
        layout.addWidget(self.breadcrumb)
        layout.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Құрылғы, модель, ID іздеу…")
        self.search.setAccessibleName("Диагностика тарихынан іздеу")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(QAction(icon("search"), "", self.search), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setFixedSize(276, 42)
        self.search.textChanged.connect(self.global_search)
        layout.addWidget(self.search)
        bell = QToolButton(objectName="notifications")
        bell.setIcon(icon("bell"))
        bell.setIconSize(QSize(20, 20))
        bell.setFixedSize(42, 42)
        bell.setAccessibleName("Хабарландырулар")
        menu = QMenu(bell)
        menu.addSection("Жүйе хабарламалары")
        user = self.ctx.user
        menu.addAction(f"Сессия басталды · {user.role_label}").setEnabled(False)
        if user.last_login_at:
            menu.addAction(f"Соңғы кіру: {fmt_local(user.last_login_at)}").setEnabled(False)
        bell.setMenu(menu)
        bell.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layout.addWidget(bell)
        if "equipment" in self.specs and self.ctx.can(Perm.DIAG_RUN):
            new = action_button("Жаңа тексеріс", "primary", 42)
            new.setIcon(icon("plus", "#ffffff"))
            new.clicked.connect(lambda: self.navigate("equipment"))
            layout.addWidget(new)
        return topbar

    # ------------------------------------------------------------------ behaviour
    def refresh_user(self):
        user = self.ctx.user
        self.avatar.setText(user.initials)
        self.user_button.setText(f"{user.full_name}\n@{user.username}")
        self.role_chip.setText(user.role_label.upper())
        self.role_chip.setProperty("role", user.role.value)
        self.role_chip.style().unpolish(self.role_chip)
        self.role_chip.style().polish(self.role_chip)

    def navigate(self, key):
        spec = self.specs.get(key)
        if spec is None:
            return
        page = self.pages[key]
        if page is self.workspace:
            self.workspace.show_section(key)
        if key in self.nav_buttons:
            self.nav_buttons[key].setChecked(True)
        else:  # profile has no sidebar entry
            self.nav_group.setExclusive(False)
            for button in self.nav_buttons.values():
                button.setChecked(False)
            self.nav_group.setExclusive(True)
        self.breadcrumb.setText(spec.title)
        self.stack.setCurrentWidget(page)
        if hasattr(page, "on_show"):
            page.on_show()
        fade_in(page)

    def global_search(self, text):
        if "history" not in self.specs:
            return
        if text:
            self.navigate("history")
        self.history.set_search(text)

    def request_logout(self):
        if confirm(self, "Жүйеден шығу керек пе?", "Шығу", "Шығу"):
            self.finish()

    def finish(self):
        if not self.ending:
            self.ending = True
            self.guard.stop()
            self.logout_requested.emit()

    def check_session(self):
        """Enforce server-side session expiry, account deactivation and role changes while the window is open."""
        if self.ending:
            return
        user = self.ctx.services.auth.validate(self.ctx.token)
        if user is None:
            self.guard.stop()
            show_info(self, "Сессия аяқталды немесе тіркелгі өшірілді. Қайта кіріңіз.")
            self.finish()
        elif user.role != self.ctx.user.role:
            self.guard.stop()
            show_info(self, "Рөліңіз өзгертілді. Жаңа құқықтарды қолдану үшін қайта кіріңіз.")
            self.finish()
        elif user != self.ctx.user:
            self.ctx.update_user(user)

    def closeEvent(self, event):
        self.guard.stop()
        self.workspace.shutdown()
        super().closeEvent(event)
