"""Login window, registration dialog and the forgot-password dialog."""
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QLabel, QLineEdit, QProgressBar, QPushButton, QScrollArea, QWidget,
)

from desktop_visuals import ASSETS, column, frame, icon, label, row

from .. import security
from ..config import APP_NAME, APP_VERSION
from ..errors import AuthError, SmartDiagnostError, ValidationError
from ..permissions import PUBLIC_ROLES, ROLE_LABELS, Role
from ..session_store import RememberStore
from ..services import Services
from .common import repolish, show_info


def text_field(icon_name, placeholder, *, password=False, accessible=""):
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    edit.setAccessibleName(accessible or placeholder)
    edit.setMinimumHeight(42)
    edit.addAction(QAction(icon(icon_name), "", edit), QLineEdit.ActionPosition.LeadingPosition)
    if password:
        edit.setEchoMode(QLineEdit.EchoMode.Password)
        toggle = QAction(icon("eye"), "Құпиясөзді көрсету", edit)
        toggle.setCheckable(True)

        def switch(shown):
            edit.setEchoMode(QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password)
            toggle.setIcon(icon("eye-off" if shown else "eye"))
            toggle.setText("Құпиясөзді жасыру" if shown else "Құпиясөзді көрсету")

        toggle.toggled.connect(switch)
        edit.addAction(toggle, QLineEdit.ActionPosition.TrailingPosition)
    return edit


def labeled(layout, caption, widget):
    heading = label(caption, "muted")
    heading.setBuddy(widget)
    layout.addWidget(heading)
    layout.addWidget(widget)


class HeroPanel(QWidget):
    """Brand side of the login screen: gradient, blueprint grid, the motor drawing and feature bullets."""

    def __init__(self):
        super().__init__()
        self.setObjectName("authHero")
        self.motor = QSvgRenderer(str(ASSETS / "motor.svg"), self)
        layout = column(self, (56, 52, 56, 48), 0)
        brand = row(spacing=12)
        mark = frame("brandMark")
        mark.setFixedSize(42, 42)
        bars = row(mark, (11, 0, 11, 9), 3)
        for height in (10, 19, 13):
            bar = frame("brandBar")
            bar.setFixedSize(3, height)
            bars.addWidget(bar, 0, Qt.AlignmentFlag.AlignBottom)
        brand.addWidget(mark)
        brand.addWidget(label('Smart<span style="color:#4fd8ee">Diagnost</span> PRO', "brandName"))
        brand.addStretch()
        layout.addLayout(brand)
        layout.addStretch(3)
        layout.addWidget(label("Қозғалтқыштар мен жабдықтарды<br>кәсіби диагностикалау", "heroTitle"))
        layout.addSpacing(14)
        layout.addWidget(label(
            "Рөлге негізделген қолжетімділік, диагностика тарихы және техникалық есептер — бір жүйеде.",
            "heroText", wrap=True))
        layout.addSpacing(26)
        for text in ("Механик · Инженер · Әкімші · Қонақ рөлдері",
                     "Диагностика тарихы SQLite базасында сақталады",
                     "PDF / TXT / CSV есептерін экспорттау"):
            layout.addWidget(label(f'<span style="color:#4fd8ee">▸</span>&nbsp; {text}', "heroBullet"))
            layout.addSpacing(6)
        layout.addStretch(4)

    def paintEvent(self, event):
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            gradient = QLinearGradient(0, 0, self.width(), self.height())
            gradient.setColorAt(0, QColor("#0b1830"))
            gradient.setColorAt(0.55, QColor("#0f1b2b"))
            gradient.setColorAt(1, QColor("#13181f"))
            painter.fillRect(self.rect(), gradient)
            painter.setPen(QPen(QColor(79, 216, 238, 16), 1))
            for x in range(0, self.width(), 32):
                painter.drawLine(x, 0, x, self.height())
            for y in range(0, self.height(), 32):
                painter.drawLine(0, y, self.width(), y)
            size = min(self.width() * 0.9, 640)
            painter.setOpacity(0.35)
            self.motor.render(painter, QRectF(self.width() - size * 0.8, self.height() - size * 0.62, size, size * 0.54))


class StrengthMeter(QWidget):
    """Live password feedback: a four-step bar plus the rules still unmet."""

    LABELS = ("Өте әлсіз", "Әлсіз", "Орташа", "Жақсы", "Күшті")

    def __init__(self):
        super().__init__()
        layout = column(self, spacing=4)
        top = row(spacing=8)
        self.bar = QProgressBar()
        self.bar.setObjectName("strength")
        self.bar.setRange(0, 4)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(5)
        self.caption = label("", "muted")
        self.caption.setMinimumWidth(70)
        top.addWidget(self.bar, 1)
        top.addWidget(self.caption)
        layout.addLayout(top)
        self.hint = label("", "muted", wrap=True)
        layout.addWidget(self.hint)

    def update_for(self, password, username="", email="", full_name=""):
        level = security.password_strength(password)
        self.bar.setValue(level)
        self.bar.setProperty("level", level)
        repolish(self.bar)
        self.caption.setText(self.LABELS[level] if password else "")
        problems = security.validate_password(password, username, email, full_name) if password else []
        self.hint.setText(" · ".join(problems[:2]) if problems else ("✓ Талаптарға сәйкес" if password else
                          "Кемінде 8 таңба, бас және кіші әріп, сан, арнайы таңба."))


def format_errors(error) -> str:
    if isinstance(error, ValidationError):
        return "\n".join(f"• {item}" for item in error.errors)
    if isinstance(error, SmartDiagnostError):
        return str(error)
    return "Күтпеген қате орын алды. Қайталап көріңіз."


class RegisterDialog(QDialog):
    """Self-registration. Roles offered are limited to PUBLIC_ROLES; the first run creates the administrator."""

    def __init__(self, services: Services, parent=None):
        super().__init__(parent)
        self.services = services
        self.setup_mode = services.auth.needs_setup()
        self.created = None
        self.setObjectName("authDialog")
        self.setWindowTitle("Бірінші әкімшіні тіркеу" if self.setup_mode else "Тіркелу")
        self.setModal(True)
        self.setMinimumWidth(520)
        layout = column(self, (30, 26, 30, 24), 9)
        layout.addWidget(label("Бірінші әкімшіні тіркеу" if self.setup_mode else "Жаңа тіркелгі", "authTitle"))
        layout.addWidget(label(
            "Жүйеде әкімші жоқ. Бұл тіркелгі толық құқықты әкімші болады." if self.setup_mode else
            f"{APP_NAME} жүйесіне қол жеткізу үшін деректеріңізді енгізіңіз.", "muted", wrap=True))
        layout.addSpacing(6)

        self.full_name = text_field("user", "Аты-жөніңіз", accessible="Толық аты-жөні")
        self.username = text_field("user", "Пайдаланушы аты (латын)", accessible="Пайдаланушы аты")
        self.email = text_field("mail", "name@example.com", accessible="Email")
        self.phone = text_field("phone", "+7 700 000 00 00", accessible="Телефон нөмірі")
        self.password = text_field("lock", "Құпиясөз", password=True, accessible="Құпиясөз")
        self.confirm = text_field("lock", "Құпиясөзді қайталаңыз", password=True, accessible="Құпиясөзді растау")
        labeled(layout, "Толық аты-жөні *", self.full_name)
        pair = row(spacing=12)
        for caption, widget in (("Пайдаланушы аты *", self.username), ("Телефон", self.phone)):
            cell = column(spacing=4)
            labeled(cell, caption, widget)
            pair.addLayout(cell, 1)
        layout.addLayout(pair)
        labeled(layout, "Email *", self.email)
        labeled(layout, "Құпиясөз *", self.password)
        self.meter = StrengthMeter()
        layout.addWidget(self.meter)
        labeled(layout, "Құпиясөзді растау *", self.confirm)

        self.role = QComboBox()
        self.role.setAccessibleName("Рөл")
        self.role.setMinimumHeight(40)
        if self.setup_mode:
            self.role.addItem(ROLE_LABELS[Role.ADMIN], Role.ADMIN)
            self.role.setEnabled(False)
        else:
            for role in PUBLIC_ROLES:
                self.role.addItem(ROLE_LABELS[role], role)
        labeled(layout, "Рөл", self.role)
        if not self.setup_mode:
            layout.addWidget(label("Инженер мен әкімші рөлін тек қолданыстағы әкімші тағайындай алады.", "micro", wrap=True))

        self.error = label("", "error", wrap=True)
        self.error.hide()
        layout.addWidget(self.error)
        layout.addSpacing(4)
        buttons = row(spacing=10)
        cancel = QPushButton("Бас тарту")
        cancel.setMinimumHeight(42)
        cancel.clicked.connect(self.reject)
        submit = QPushButton("Тіркелу")
        submit.setObjectName("primary")
        submit.setMinimumHeight(42)
        submit.setDefault(True)
        submit.clicked.connect(self.submit)
        buttons.addWidget(cancel)
        buttons.addWidget(submit, 1)
        layout.addLayout(buttons)
        for edit in (self.full_name, self.username, self.email, self.password):
            edit.textChanged.connect(self.refresh_meter)

    def refresh_meter(self):
        self.meter.update_for(self.password.text(), self.username.text(), self.email.text(), self.full_name.text())

    def submit(self):
        try:
            self.created = self.services.auth.register(
                full_name=self.full_name.text(), username=self.username.text(), email=self.email.text(),
                phone=self.phone.text(), password=self.password.text(), confirm_password=self.confirm.text(),
                role=self.role.currentData(),
            )
        except Exception as error:  # noqa: BLE001 - every failure is mapped to a friendly message
            self.error.setText(format_errors(error))
            self.error.show()
            return
        self.password.clear()
        self.confirm.clear()
        self.accept()


class ForgotPasswordDialog(QDialog):
    """Reset with a one-time code issued by an administrator (the app has no mail server)."""

    def __init__(self, services: Services, identifier="", parent=None):
        super().__init__(parent)
        self.services = services
        self.setObjectName("authDialog")
        self.setWindowTitle("Құпиясөзді қалпына келтіру")
        self.setModal(True)
        self.setMinimumWidth(460)
        layout = column(self, (30, 26, 30, 24), 9)
        layout.addWidget(label("Құпиясөзді қалпына келтіру", "authTitle"))
        layout.addWidget(label(
            "Әкімшіге хабарласып, бір реттік қалпына келтіру кодын алыңыз (30 минут жарамды). "
            "Кодты және жаңа құпиясөзді төменде енгізіңіз.", "muted", wrap=True))
        layout.addSpacing(6)
        self.identifier = text_field("user", "Пайдаланушы аты немесе email")
        self.identifier.setText(identifier)
        self.code = text_field("key", "XXXX-XXXX", accessible="Қалпына келтіру коды")
        self.password = text_field("lock", "Жаңа құпиясөз", password=True)
        self.confirm = text_field("lock", "Жаңа құпиясөзді қайталаңыз", password=True)
        labeled(layout, "Пайдаланушы аты немесе email", self.identifier)
        labeled(layout, "Қалпына келтіру коды", self.code)
        labeled(layout, "Жаңа құпиясөз", self.password)
        self.meter = StrengthMeter()
        layout.addWidget(self.meter)
        labeled(layout, "Құпиясөзді растау", self.confirm)
        self.password.textChanged.connect(lambda: self.meter.update_for(self.password.text()))
        self.error = label("", "error", wrap=True)
        self.error.hide()
        layout.addWidget(self.error)
        buttons = row(spacing=10)
        cancel = QPushButton("Бас тарту")
        cancel.setMinimumHeight(42)
        cancel.clicked.connect(self.reject)
        submit = QPushButton("Құпиясөзді өзгерту")
        submit.setObjectName("primary")
        submit.setMinimumHeight(42)
        submit.setDefault(True)
        submit.clicked.connect(self.submit)
        buttons.addWidget(cancel)
        buttons.addWidget(submit, 1)
        layout.addLayout(buttons)

    def submit(self):
        try:
            self.services.auth.reset_password(
                self.identifier.text(), self.code.text(), self.password.text(), self.confirm.text())
        except Exception as error:  # noqa: BLE001
            self.error.setText(format_errors(error))
            self.error.show()
            return
        self.accept()


class LoginWindow(QWidget):
    authenticated = Signal(object)

    def __init__(self, services: Services, store: RememberStore):
        super().__init__()
        self.services, self.store = services, store
        self.setObjectName("authRoot")
        self.setWindowTitle(f"{APP_NAME} · Кіру")
        self.setMinimumSize(520, 640)
        self.resize(1120, 740)

        root = row(self)
        self.hero = HeroPanel()
        root.addWidget(self.hero, 5)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setObjectName("authScroll")
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        holder = QWidget()
        holder.setObjectName("authSide")
        scroll.setWidget(holder)
        outer = column(holder, (24, 24, 24, 24), 0)
        outer.addStretch(1)
        card = frame("authCard")
        card.setMaximumWidth(440)
        outer.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)
        root.addWidget(scroll, 4)

        form = column(card, (34, 34, 34, 28), 10)
        form.addWidget(label("Қош келдіңіз", "authTitle"))
        form.addWidget(label(f"{APP_NAME} жүйесіне кіріңіз", "muted"))
        form.addSpacing(8)
        self.banner = frame("notice")
        banner_row = row(self.banner, (12, 9, 12, 9))
        banner_row.addWidget(label(
            "Жүйеде әкімші жоқ. Бастау үшін бірінші әкімші тіркелгісін жасаңыз.", "accent", wrap=True))
        form.addWidget(self.banner)

        self.identifier = text_field("user", "Пайдаланушы аты немесе email", accessible="Пайдаланушы аты немесе email")
        self.password = text_field("lock", "Құпиясөз", password=True, accessible="Құпиясөз")
        labeled(form, "Пайдаланушы аты немесе email", self.identifier)
        labeled(form, "Құпиясөз", self.password)
        options = row(spacing=8)
        self.remember = QCheckBox("Мені есте сақта")
        forgot = QPushButton("Құпиясөзді ұмыттыңыз ба?")
        forgot.setObjectName("link")
        forgot.setCursor(Qt.CursorShape.PointingHandCursor)
        forgot.clicked.connect(self.open_forgot)
        options.addWidget(self.remember)
        options.addStretch()
        options.addWidget(forgot)
        form.addLayout(options)
        self.error = label("", "error", wrap=True)
        self.error.setMinimumHeight(58)  # wrapped labels inside a scroll area do not grow on their own
        self.error.hide()
        form.addWidget(self.error)
        form.addSpacing(4)
        self.login_button = QPushButton("Кіру")
        self.login_button.setObjectName("primary")
        self.login_button.setMinimumHeight(46)
        self.login_button.setDefault(True)
        self.login_button.clicked.connect(self.attempt_login)
        form.addWidget(self.login_button)
        or_row = row(spacing=10)
        for part in (frame("divider"), label("немесе", "muted"), frame("divider")):
            if isinstance(part, QLabel):
                or_row.addWidget(part)
            else:
                part.setFixedHeight(1)
                or_row.addWidget(part, 1)
        form.addLayout(or_row)
        self.register_button = QPushButton("Тіркелу")
        self.register_button.setObjectName("outline")
        self.register_button.setMinimumHeight(44)
        self.register_button.clicked.connect(self.open_register)
        form.addWidget(self.register_button)
        form.addSpacing(6)
        form.addWidget(label(f"{APP_NAME} · v{APP_VERSION}", "micro"), 0, Qt.AlignmentFlag.AlignHCenter)

        self.identifier.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self.attempt_login)
        self.refresh_state()

    def resizeEvent(self, event):
        self.hero.setVisible(self.width() >= 900)  # responsive: drop the brand panel on narrow windows
        super().resizeEvent(event)

    def refresh_state(self):
        setup = self.services.auth.needs_setup()
        self.banner.setVisible(setup)
        self.register_button.setText("Бірінші әкімшіні тіркеу" if setup else "Тіркелу")
        self.error.hide()

    def show_error(self, message):
        self.error.setText(message)
        self.error.show()

    def reset_form(self):
        self.password.clear()
        self.error.hide()
        self.refresh_state()
        self.password.setFocus() if self.identifier.text() else self.identifier.setFocus()

    def attempt_login(self):
        self.login_button.setEnabled(False)
        try:
            session = self.services.auth.login(self.identifier.text(), self.password.text(), self.remember.isChecked())
        except AuthError as error:
            self.show_error(str(error))
            self.password.selectAll()
            self.password.setFocus()
            return
        except Exception:  # noqa: BLE001
            self.show_error("Кіру кезінде қате орын алды. Деректер қорын тексеріп, қайталаңыз.")
            return
        finally:
            self.login_button.setEnabled(True)
        self.password.clear()
        self.error.hide()
        self.authenticated.emit(session)

    def open_register(self):
        dialog = RegisterDialog(self.services, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.created:
            self.identifier.setText(dialog.created.username)
            self.refresh_state()
            show_info(self, f"Тіркелу сәтті аяқталды. «{dialog.created.username}» атымен кіре аласыз.")
            self.password.setFocus()

    def open_forgot(self):
        dialog = ForgotPasswordDialog(self.services, self.identifier.text(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.identifier.setText(dialog.identifier.text())
            show_info(self, "Құпиясөз өзгертілді. Жаңа құпиясөзбен кіріңіз.")
            self.password.setFocus()
