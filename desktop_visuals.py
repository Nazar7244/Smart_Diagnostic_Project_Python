import math
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


PUBLIC = Path(__file__).resolve().parent / "public"
ASSETS = PUBLIC / "assets"


@dataclass(frozen=True)
class Reading:
    name: str
    number: str
    unit: str
    short_name: str = ""

    @property
    def value(self):
        return f"{self.number} {self.unit}"

    @property
    def caption(self):
        return self.short_name or self.name


@dataclass(frozen=True)
class Sensor:
    x: int
    y: int
    text_x: int
    text_y: int
    reading: Reading


@dataclass(frozen=True)
class Engine:
    id: str
    name: str
    kind: str
    asset: str
    sensors: tuple[Sensor, ...]
    metrics: tuple[Reading, ...]
    assessment: tuple[str, str, str] = ("Демо", "—", "Баға жоқ")


motor_temperature = Reading("Температура", "45", "°C")
motor_vibration = Reading("Діріл", "1.2", "G")
coolant_temperature = Reading("Салқындатқыш температурасы", "88", "°C", "Салқындатқыш")
oil_pressure = Reading("Май қысымы", "3.2", "бар")
car_speed = Reading("Айналым жиілігі", "2800", "RPM", "Айналым")
fan_speed = Reading("Желдеткіш айналымы", "3800", "RPM", "Желдеткіш")
gas_temperature = Reading("Шығатын газ температурасы", "650", "°C", "Газ температурасы")
turbofan_vibration = Reading("Діріл", "1.8", "G")

ENGINES = (
    Engine(
        "M-4000", "Электр қозғалтқышы", "Электр қозғалтқышы", "motor.svg",
        (
            Sensor(306, 77, 370, 43, motor_temperature),
            Sensor(195, 176, 17, 123, Reading("Магниттік өріс", "0.42", "T")),
            Sensor(326, 175, 405, 152, motor_vibration),
            Sensor(367, 242, 408, 280, Reading("Айналу моменті", "12.8", "N·m")),
        ),
        (motor_temperature, motor_vibration, Reading("Жылдамдық", "1500", "RPM")),
        ("Қалыпты", "98.7%", "Өте жақсы"),
    ),
    Engine(
        "AUTO-2800", "Автокөлік қозғалтқышы", "Бензинді қозғалтқыш", "car-engine.svg",
        (
            Sensor(182, 133, 20, 105, coolant_temperature),
            Sensor(397, 161, 453, 137, oil_pressure),
            Sensor(448, 230, 472, 265, car_speed),
        ),
        (coolant_temperature, oil_pressure, car_speed),
    ),
    Engine(
        "TF-3800", "Ұшақ қозғалтқышы", "Турбожелдеткіш қозғалтқыш", "turbofan.svg",
        (
            Sensor(160, 166, 51, 40, fan_speed),
            Sensor(343, 129, 434, 59, gas_temperature),
            Sensor(343, 205, 434, 252, turbofan_vibration),
        ),
        (gas_temperature, turbofan_vibration, fan_speed),
    ),
)

ICON_PATHS = {
    "grid": "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
    "pulse": "M3 12h4l2.2-6 4.1 12L16 9l1.5 3H21",
    "report": "M6 3h9l3 3v15H6zM14 3v4h4M9 12h6M9 16h6",
    "settings": "M9 3h6l1 3 3 1 2 4-2 2v3l-3 2-1 3H9l-1-3-3-1-2-4 2-2V8l3-2zM15 12a3 3 0 1 0-6 0 3 3 0 1 0 6 0",
    "search": "M17 10a7 7 0 1 0-14 0 7 7 0 1 0 14 0M15 15l5 5",
    "bell": "M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4",
    "plus": "M12 5v14M5 12h14",
    # SmartDiagnost PRO additions
    "eye": "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM15 12a3 3 0 1 0-6 0 3 3 0 1 0 6 0",
    "eye-off": "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM15 12a3 3 0 1 0-6 0 3 3 0 1 0 6 0M3 3l18 18",
    "user": "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M16 7a4 4 0 1 0-8 0 4 4 0 1 0 8 0",
    "users": "M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M13 7a4 4 0 1 0-8 0 4 4 0 1 0 8 0M23 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8",
    "lock": "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
    "mail": "M3 5h18v14H3zM3 6l9 7 9-7",
    "phone": "M5 3h4l2 5-2.5 1.5a11 11 0 0 0 6 6L16 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 5a2 2 0 0 1 2-2",
    "logout": "M9 21H5V3h4M16 17l5-5-5-5M21 12H9",
    "history": "M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2",
    "flask": "M9 3h6M10 3v6L4 19a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-6-10V3M7 15h10",
    "wrench": "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.5-.5-.5-2.5z",
    "sliders": "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6",
    "download": "M12 3v12M7 10l5 5 5-5M4 21h16",
    "trash": "M4 7h16M10 11v6M14 11v6M5 7l1 14h12l1-14M9 7V4h6v3",
    "shield": "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
    "key": "M15 7a4 4 0 1 0-1 2.6L3 20v-3h3v-3h3l2-2",
    "check": "M5 12l5 5L20 7",
}


def icon(name, color="#a2b3c6"):
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
      <path d="{ICON_PATHS[name]}" fill="none" stroke="{color}" stroke-width="1.7"
        stroke-linecap="round" stroke-linejoin="round"/>
    </svg>"""
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    with QPainter(pixmap) as painter:
        renderer.render(painter)
    return QIcon(pixmap)


def label(text, role="", wrap=False):
    widget = QLabel(text)
    if role:
        widget.setObjectName(role)
    widget.setWordWrap(wrap)
    return widget


def frame(name="panel"):
    widget = QFrame()
    widget.setObjectName(name)
    return widget


def column(parent=None, margins=(0, 0, 0, 0), spacing=0):
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def row(parent=None, margins=(0, 0, 0, 0), spacing=0):
    layout = QHBoxLayout(parent)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


class MotorDiagram(QWidget):
    sensor_changed = Signal(int)

    def __init__(self, engine):
        super().__init__()
        self.sensor = 0
        self.motor = QSvgRenderer(self)
        self.setMinimumSize(260, 238)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("Датчикті басыңыз немесе бағыттау пернелерімен ауыстырыңыз.")
        self.set_engine(engine)

    def set_engine(self, engine):
        self.engine = engine
        self.motor.load(str(ASSETS / engine.asset))
        self.setAccessibleName(f"{engine.name} · интерактивті сызба")
        self.select_sensor(0)

    def drawing_rect(self):
        scale = min(self.width() / 590, self.height() / 320)
        width, height = 590 * scale, 320 * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def select_sensor(self, index):
        self.sensor = index
        self.sensor_changed.emit(index)
        self.update()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.select_sensor((self.sensor - 1) % len(self.engine.sensors))
        elif event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.select_sensor((self.sensor + 1) % len(self.engine.sensors))
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            rect = self.drawing_rect()
            point = (event.position() - rect.topLeft()) * (590 / rect.width())
            for index, sensor in enumerate(self.engine.sensors):
                if math.hypot(point.x() - sensor.x, point.y() - sensor.y) < 29:
                    self.select_sensor(index)
                    return
            for index, sensor in enumerate(self.engine.sensors):
                if QRectF(sensor.text_x, sensor.text_y - 12, 110, 31).contains(point):
                    self.select_sensor(index)
                    return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        rect = self.drawing_rect()
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.translate(rect.topLeft())
            painter.scale(rect.width() / 590, rect.height() / 320)
            painter.setPen(QPen(QColor("#192735"), 0.55))
            for x in range(0, 590, 24):
                painter.drawLine(x, 0, x, 320)
            for y in range(0, 320, 24):
                painter.drawLine(0, y, 590, y)
            self.motor.render(painter, QRectF(0, 0, 590, 320))
            font = painter.font()
            if self.engine.asset == "motor.svg":
                font.setPixelSize(9)
                painter.setFont(font)
                painter.setPen(QColor("#7895ae"))
                painter.drawText(QPointF(91, 209), "АУА АҒЫНЫ")
            for index, sensor in enumerate(self.engine.sensors):
                center = QPointF(sensor.x, sensor.y)
                offset = max(-35, min(35, sensor.text_x - sensor.x))
                elbow = QPointF(sensor.x + offset, sensor.text_y + 10)
                painter.setPen(QPen(QColor("#46748c"), 0.8))
                painter.drawLine(center, elbow)
                painter.drawLine(elbow, QPointF(sensor.text_x, elbow.y()))
                glow = QRadialGradient(center, 29)
                glow.setColorAt(0, QColor(118, 237, 255, 165))
                glow.setColorAt(1, QColor(77, 200, 249, 0))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow)
                painter.drawEllipse(center, 29, 29)
                painter.setPen(QPen(QColor("#75d9ec"), 1))
                painter.setBrush(QColor("#275869"))
                painter.drawEllipse(center, 10, 10)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#a1eff7"))
                painter.drawEllipse(center, 5, 5)
                if self.sensor == index:
                    painter.setPen(QPen(QColor("#94d8e5"), 1))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(center, 28, 28)
                font.setPixelSize(10)
                painter.setFont(font)
                painter.setPen(QColor("#a1b5c9"))
                painter.drawText(QPointF(sensor.text_x, sensor.text_y), sensor.reading.caption)
                font.setPixelSize(11)
                painter.setFont(font)
                painter.setPen(QColor("#d0e6f4"))
                painter.drawText(QPointF(sensor.text_x, sensor.text_y + 15), sensor.reading.value)


class PerformanceChart(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(66)
        self.setAccessibleName("Демо өнімділік графигі")

    def paintEvent(self, event):
        points = (19, 21, 18, 20, 15, 17, 13, 15, 12, 14, 10, 13, 9, 11, 8, 10, 6, 8, 5)
        width, height = self.width(), self.height() - 1
        line = QPainterPath(QPointF(0, points[0]))
        for index, y in enumerate(points[1:], 1):
            line.lineTo(index * width / (len(points) - 1), y)
        area = QPainterPath(line)
        area.lineTo(width, height)
        area.lineTo(0, height)
        area.closeSubpath()
        fill = QLinearGradient(0, 0, 0, height)
        fill.setColorAt(0, QColor(77, 155, 244, 51))
        fill.setColorAt(1, QColor(77, 155, 244, 0))
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillPath(area, fill)
            painter.strokePath(line, QPen(QColor("#5dabe7"), 1.25))
            painter.setPen(QColor("#253447"))
            painter.drawLine(0, height, width, height)


class Waveform(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(56)
        self.phase = 0
        self.recording = False

    def paintEvent(self, event):
        width, center = self.width(), self.height() / 2
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            color = "#62b8ff" if self.recording else "#357eb7"
            pen = QPen(QColor(color), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            for index in range(38):
                x = (index + 0.5) * width / 38
                i = index + self.phase
                height = (8 + abs(math.sin(i * 1.8) * math.cos(i * 0.4)) * 39) / 2
                painter.drawLine(QPointF(x, center - height), QPointF(x, center + height))
