"""Shared widgets and helpers for the SmartDiagnost PRO screens."""
from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFileDialog, QFrame, QGraphicsOpacityEffect, QLabel, QMessageBox, QWidget

from desktop_visuals import column, frame, label, row

from ..errors import SmartDiagnostError, ValidationError
from ..models import STATUS_LABELS

# Status colours are reserved for status: they always travel with a glyph and a text label.
STATUS_COLORS = {"success": "#59cfa2", "warning": "#f4ba77", "failed": "#f2788a", "pending": "#7cb8f0"}
STATUS_GLYPHS = {"success": "✓", "warning": "!", "failed": "✕", "pending": "…"}


def repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def status_badge(status: str) -> QLabel:
    badge = QLabel(f"{STATUS_GLYPHS[status]}  {STATUS_LABELS[status]}")
    badge.setObjectName("badge")
    badge.setProperty("state", status)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return badge


def set_badge(badge: QLabel, status: str):
    badge.setText(f"{STATUS_GLYPHS[status]}  {STATUS_LABELS[status]}")
    badge.setProperty("state", status)
    repolish(badge)


def role_badge(text: str, role_key: str) -> QLabel:
    badge = QLabel(text)
    badge.setObjectName("roleBadge")
    badge.setProperty("role", role_key)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return badge


def page_header(title: str, subtitle: str = "") -> QWidget:
    holder = QWidget()
    layout = column(holder, spacing=4)
    layout.addWidget(label(title, "pageTitle"))
    if subtitle:
        layout.addWidget(label(subtitle, "muted", wrap=True))
    return holder


class StatCard(QFrame):
    """KPI tile: caption, big number, hint. Colour is carried by the accent strip only; text stays in ink."""

    def __init__(self, caption: str, accent: str = "#4fd8ee", hint: str = ""):
        super().__init__()
        self.setObjectName("statCard")
        self.setMinimumHeight(104)
        layout = column(self, (18, 14, 16, 14), 4)
        strip = QFrame(self)
        strip.setObjectName("statStrip")
        strip.setStyleSheet(f"background:{accent};border-radius:2px;")
        strip.setFixedSize(26, 3)
        layout.addWidget(strip)
        layout.addSpacing(5)
        layout.addWidget(label(caption.upper(), "micro"))
        self.value = label("—", "statValue")
        layout.addWidget(self.value)
        self.hint = label(hint, "muted", wrap=True)
        layout.addWidget(self.hint)

    def set(self, value, hint=None):
        self.value.setText(str(value))
        if hint is not None:
            self.hint.setText(hint)


class StatusBar(QWidget):
    """One stacked bar (2px gaps between segments) plus a legend with counts, so colour is never the only cue."""

    ORDER = ("success", "warning", "failed", "pending")

    def __init__(self):
        super().__init__()
        self.counts = dict.fromkeys(self.ORDER, 0)
        layout = column(self, spacing=8)
        self.bar = _Segments(self)
        layout.addWidget(self.bar)
        self.legend = label("", "muted", wrap=True)
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.legend)
        self.set_counts(self.counts)

    def set_counts(self, counts: dict):
        self.counts = {key: counts.get(key, 0) for key in self.ORDER}
        self.bar.counts = self.counts
        self.bar.update()
        self.legend.setText("&nbsp;&nbsp;&nbsp;".join(
            f'<span style="color:{STATUS_COLORS[k]}">●</span> {STATUS_LABELS[k]} <b>{self.counts[k]}</b>'
            for k in self.ORDER
        ))


class _Segments(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.counts = {}
        self.setFixedHeight(10)

    def paintEvent(self, event):
        total = sum(self.counts.values())
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            full = QRectF(0, 0, self.width(), self.height())
            clip = QPainterPath()
            clip.addRoundedRect(full, 3, 3)
            painter.setClipPath(clip)
            painter.fillRect(full, QColor("#1a2634"))
            if not total:
                return
            x, gap = 0.0, 2.0
            shown = [(k, v) for k, v in self.counts.items() if v]
            usable = self.width() - gap * (len(shown) - 1)
            for key, value in shown:
                width = usable * value / total
                painter.fillRect(QRectF(x, 0, width, self.height()), QColor(STATUS_COLORS[key]))
                x += width + gap


class Sparkline(QWidget):
    """Trend of one parameter over saved tests, drawn over the shaded nominal range."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(120)
        self.values, self.low, self.high, self.unit = [], None, None, ""
        self.setAccessibleName("Параметр трендісі")

    def set_data(self, values, low=None, high=None, unit=""):
        self.values, self.low, self.high, self.unit = list(values), low, high, unit
        self.update()

    def paintEvent(self, event):
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = QRectF(8, 10, self.width() - 16, self.height() - 22)
            if not self.values:
                painter.setPen(QColor("#829bb3"))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Сақталған тест жоқ")
                return
            points = list(self.values)
            lo, hi = min(points), max(points)
            if self.low is not None:
                lo, hi = min(lo, self.low), max(hi, self.high)
            pad = (hi - lo) * 0.12 or 1.0
            lo, hi = lo - pad, hi + pad

            def y_of(value):
                return rect.bottom() - (value - lo) / (hi - lo) * rect.height()

            if self.low is not None:
                band = QRectF(rect.left(), y_of(self.high), rect.width(), y_of(self.low) - y_of(self.high))
                painter.fillRect(band, QColor(79, 216, 238, 28))
                painter.setPen(QPen(QColor("#2a5262"), 1, Qt.PenStyle.DashLine))
                painter.drawLine(band.topLeft(), band.topRight())
                painter.drawLine(band.bottomLeft(), band.bottomRight())
            step = rect.width() / max(1, len(points) - 1)
            coords = [QPointF(rect.left() + i * step if len(points) > 1 else rect.center().x(), y_of(v))
                      for i, v in enumerate(points)]
            pen = QPen(QColor("#5dabe7"), 2)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            for a, b in zip(coords, coords[1:]):
                painter.drawLine(a, b)
            for index, point in enumerate(coords):
                outside = self.low is not None and not self.low <= points[index] <= self.high
                painter.setPen(QPen(QColor("#0f1720"), 2))
                painter.setBrush(QColor("#f2788a" if outside else "#8de8f5"))
                painter.drawEllipse(point, 4.5, 4.5)
            font = QFont(painter.font())
            font.setPixelSize(10)
            painter.setFont(font)
            painter.setPen(QColor("#b9cee3"))
            painter.drawText(QPointF(rect.left(), self.height() - 3), f"Соңғы: {points[-1]:g} {self.unit}   ·   {len(points)} тест")


def fade_in(widget: QWidget, duration=180):
    """Short opacity transition used when switching pages."""
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.finished.connect(lambda: widget.setGraphicsEffect(None))
    widget._fade = animation  # keep a reference alive
    animation.start()


# ------------------------------------------------------------------ dialog helpers

def _box(parent, icon, title, text) -> QMessageBox:
    box = QMessageBox(icon, title, text, QMessageBox.StandardButton.Ok, parent)
    box.setTextFormat(Qt.TextFormat.PlainText)
    return box


def show_info(parent, text, title="SmartDiagnost"):
    _box(parent, QMessageBox.Icon.Information, title, text).exec()


def show_error(parent, error, title="Қате"):
    """Show a user-facing error. Unexpected exceptions are summarised, never dumped as tracebacks."""
    if isinstance(error, ValidationError):
        text = "\n".join(f"• {item}" for item in error.errors)
    elif isinstance(error, SmartDiagnostError):
        text = str(error)
    else:
        text = "Күтпеген қате орын алды. Әрекетті қайталап көріңіз."
    _box(parent, QMessageBox.Icon.Warning, title, text).exec()


def confirm(parent, text, yes="Иә", title="Растау") -> bool:
    box = QMessageBox(QMessageBox.Icon.Question, title, text, QMessageBox.StandardButton.NoButton, parent)
    box.setTextFormat(Qt.TextFormat.PlainText)
    accept = box.addButton(yes, QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Бас тарту", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is accept


def pick_save_path(parent, title, default_name, filters):
    path, chosen = QFileDialog.getSaveFileName(parent, title, default_name, filters)
    return path, chosen


def fmt_local(moment, fmt="dd.MM.yyyy HH:mm"):
    """Format an aware datetime in the user's local time using Qt-style tokens."""
    local = moment.astimezone()
    return (fmt.replace("dd", f"{local.day:02d}").replace("MM", f"{local.month:02d}")
               .replace("yyyy", f"{local.year}").replace("HH", f"{local.hour:02d}")
               .replace("mm", f"{local.minute:02d}").replace("ss", f"{local.second:02d}"))


def separator():
    line = frame("divider")
    line.setFixedHeight(1)
    return line



# ------------------------------------------------------------------ helpers carried over from the original main.py

def divider():
    return separator()


def progress(value=995):
    from PySide6.QtWidgets import QProgressBar
    bar = QProgressBar()
    bar.setRange(0, 1000)
    bar.setValue(value)
    bar.setTextVisible(False)
    bar.setFixedHeight(4)
    return bar


def centered_badge(text, role, size):
    widget = label(text, role)
    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    widget.setFixedSize(size, size)
    return widget


def field(layout, text, widget):
    caption = label(text, "muted")
    caption.setBuddy(widget)
    layout.addWidget(caption)
    layout.addWidget(widget)
    widget.setAccessibleName(text)


def action_button(text, role, height=36):
    from PySide6.QtWidgets import QPushButton
    button = QPushButton(text)
    button.setObjectName(role)
    button.setMinimumHeight(height)
    return button


def make_panel(title, subtitle, tag="", ctx=None, technical=False, height=76, action=None):
    """Titled card with a header row (the original SmartDiagnost `panel`)."""
    card = frame()
    body = column(card)
    header = frame("header")
    header.setFixedHeight(height)
    line = row(header, (20, 0, 18, 0), 8)
    headings = column(spacing=4)
    headings.addWidget(label(title, "title"))
    if subtitle is not None:  # None = title only (vertically centred); "" = placeholder the caller fills in later
        headings.addWidget(ctx.technical(subtitle) if (technical and ctx is not None) else label(subtitle, "muted"))
    line.addLayout(headings, 1)
    line.setAlignment(headings, Qt.AlignmentFlag.AlignVCenter)
    if action is not None:
        line.addWidget(action, 0, Qt.AlignmentFlag.AlignVCenter)
    if tag:
        line.addWidget(label(tag, "tag"), 0, Qt.AlignmentFlag.AlignVCenter)
    body.addWidget(header)
    return card, body


def fit_table(table, rows, row_height=34):
    """Size a read-only table to its rows so it never shows an inner scrollbar; headers align with the cells."""
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    table.verticalHeader().setDefaultSectionSize(row_height)
    table.setFixedHeight(table.horizontalHeader().sizeHint().height() + rows * row_height + 4)
