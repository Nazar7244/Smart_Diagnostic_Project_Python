"""The original SmartDiagnost diagnostic workspace (digital twin, AI analysis, signal recorder, new check, preferences).

Moved here from main.py with its behaviour unchanged. What changed:
* the sidebar/topbar moved to the application shell (shell.py);
* the in-memory history table and editor were replaced by the database-backed History page;
* "new check" now stores the equipment and a pending diagnostic in SQLite;
* actions that run diagnostics are gated by the user's role.
"""
import json
import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QComboBox, QLabel, QLineEdit, QPlainTextEdit, QScrollArea, QToolButton, QWidget,
)

from desktop_audio import SignalRecorder
from desktop_visuals import ENGINES, ASSETS, MotorDiagram, PerformanceChart, column, frame, label, row

from ..config import CATEGORIES
from ..errors import SmartDiagnostError
from ..permissions import Perm
from .common import action_button, centered_badge, divider, field, make_panel, show_error
from .test_runner import TestRunnerPanel

ENGINE, EQUIPMENT, SETTINGS = "engine", "equipment", "settings"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_AI_MODEL = "google/gemma-4-26b-a4b-it:free"
AI_ERRORS = {
    400: "OpenRouter сұрауды қабылдамады. Модель ID-ін тексеріңіз.",
    401: "API кілті жарамсыз. PowerShell-де кілтті қайта енгізіңіз.",
    402: "Бұл сұрауға OpenRouter балансы жеткіліксіз.",
    403: "Бұл модельге немесе сұрауға рұқсат берілмеді.",
    404: "Модель табылмады. OPENROUTER_MODEL мәнін тексеріңіз.",
    429: "Сұрау лимитіне жетті. Біраздан соң қайталап көріңіз.",
    503: "Модель уақытша қолжетімсіз. Кейін қайталап көріңіз.",
}


class DiagnosticWorkspace(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.can_run = ctx.can(Perm.DIAG_RUN)
        self.engine = ENGINES[0]
        self.ai_model = os.getenv("OPENROUTER_MODEL", "").strip() or DEFAULT_AI_MODEL
        self.ai_reply = None
        self.ai_network = QNetworkAccessManager(self)
        self.ai_network.finished.connect(self.show_ai_result)

        outer = column(self)
        self.scroll = QScrollArea(widgetResizable=True)
        outer.addWidget(self.scroll)
        surface = QWidget()
        surface.setObjectName("surface")
        self.scroll.setWidget(surface)
        layout = column(surface, (24, 20, 20, 17), 15)

        self.notice = frame("notice")
        notice_row = row(self.notice, (12, 6, 6, 6), 10)
        self.notice_text = label("", "accent", wrap=True)
        notice_row.addWidget(self.notice_text, 1)
        close_notice = QToolButton(text="×")
        close_notice.setAccessibleName("Хабарламаны жабу")
        close_notice.clicked.connect(self.notice.hide)
        notice_row.addWidget(close_notice)
        layout.addWidget(self.notice)
        self.notice.hide()

        self.demo_banner = frame("notice")
        row(self.demo_banner, (14, 10, 14, 10)).addWidget(label(
            "Демо режим · Сіз үлгі деректерді көре аласыз. Диагностика тесттерін іске қосу, жазу және сақтау қолжетімсіз.",
            "accent", wrap=True))
        layout.addWidget(self.demo_banner)
        self.demo_banner.setVisible(not self.can_run)

        upper = row(spacing=15)
        self.overview = self.build_overview()
        upper.addWidget(self.overview, 1, Qt.AlignmentFlag.AlignTop)
        self.runner = TestRunnerPanel(ctx)
        upper.addWidget(self.runner, 1, Qt.AlignmentFlag.AlignTop)
        self.acquisition = QWidget()
        acquisition = column(self.acquisition, spacing=20)
        self.new_check = self.build_new_check()
        acquisition.addWidget(self.new_check)
        self.record_panel, record_body = make_panel(
            "Сигнал жазу", "SIGNAL ACQUISITION", "WAV · MP3", ctx=ctx, technical=True, height=66)
        self.recorder = SignalRecorder()
        record_body.addWidget(self.recorder)
        acquisition.addWidget(self.record_panel)
        acquisition.addStretch()
        upper.addWidget(self.acquisition)
        layout.addLayout(upper)

        lower = row(spacing=15)
        self.preferences = self.build_preferences()
        lower.addWidget(self.preferences, 1, Qt.AlignmentFlag.AlignTop)
        lower.addStretch(2)
        layout.addLayout(lower)

        footer = row(spacing=12)
        footer.addWidget(label("●  SmartDiagnost Engine v2.4", "muted"))
        footer.addStretch()
        footer.addWidget(label("Демо деректері · Нақты диагностика жүйесіне қосылмаған", "muted"))
        footer.addStretch()
        footer.addWidget(ctx.technical("LOCAL WORKSPACE"))
        layout.addLayout(footer)
        layout.addStretch()

        # Recording and AI analysis need the "run diagnostics" permission.
        self.recorder.setEnabled(self.can_run)
        self.ai_button.setEnabled(self.can_run)
        self.show_section(ENGINE)

    # ------------------------------------------------------------------ digital twin (unchanged behaviour)
    def build_overview(self):
        self.engine_picker = QComboBox()
        self.engine_picker.setAccessibleName("Қозғалтқышты таңдау")
        self.engine_picker.addItems([engine.name for engine in ENGINES])
        self.engine_picker.setFixedWidth(165)
        panel, layout = make_panel("Жүйе күйі", "", "●  DEMO LIVE", action=self.engine_picker)
        self.engine_detail = panel.findChild(QLabel, "muted")
        self.engine_detail.setWordWrap(True)
        panel.setFixedHeight(736)
        panel.setMinimumWidth(510)
        metrics = QWidget()
        metrics.setFixedHeight(125)
        strip = row(metrics, (18, 0, 18, 0), 13)
        self.engine_condition = label("", "green")
        self.engine_health = label("", "accent")
        self.health_badge = centered_badge("", "health", 42)
        for badge, caption, description in (
            (centered_badge("●", "normal", 42), "ЖАЛПЫ КҮЙІ", self.engine_condition),
            (self.health_badge, "ДЕНСАУЛЫҚ", self.engine_health),
        ):
            indicator = row(spacing=8)
            indicator.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
            details = column(spacing=4)
            details.addWidget(label(caption, "micro"))
            details.addWidget(description)
            indicator.addLayout(details)
            indicator.setAlignment(details, Qt.AlignmentFlag.AlignVCenter)
            strip.addLayout(indicator)
            strip.addStretch()
        self.engine_metrics = []
        for _ in self.engine.metrics:
            metric = column(spacing=4)
            widgets = (label("", "micro"), label("", "metric"), label("", "hint"))
            self.engine_metrics.append(widgets)
            for widget in widgets:
                metric.addWidget(widget)
            strip.addLayout(metric)
            strip.setAlignment(metric, Qt.AlignmentFlag.AlignVCenter)
            strip.addStretch()
        layout.addWidget(metrics)
        layout.addWidget(divider())

        twin = row(margins=(14, 17, 16, 13), spacing=14)
        diagram = column(spacing=1)
        caption = row(margins=(5, 0, 4, 0))
        self.diagram_title = self.ctx.technical("")
        caption.addWidget(self.diagram_title)
        caption.addStretch()
        caption.addWidget(label("●  LIVE", "green"))
        diagram.addLayout(caption)
        self.motor = MotorDiagram(self.engine)
        diagram.addWidget(self.motor, 1)
        readout = frame("readout")
        readout.setFixedHeight(38)
        readout_row = row(readout, (10, 0, 10, 0), 7)
        self.sensor_name = label("", "accent", wrap=True)
        self.sensor_value = label("", "accent")
        readout_row.addWidget(self.sensor_name, 1)
        readout_row.addWidget(self.sensor_value)
        diagram.addWidget(readout)
        self.motor.sensor_changed.connect(self.show_sensor)
        twin.addLayout(diagram, 1)
        twin.addWidget(self.build_ai())
        layout.addLayout(twin, 1)

        performance = column(margins=(23, 0, 23, 16), spacing=6)
        performance.addWidget(divider())
        performance.addSpacing(5)
        chart_heading = row()
        chart_heading.addWidget(label("Өнімділік динамикасы · демо", "muted"))
        chart_heading.addStretch()
        chart_heading.addWidget(label("Соңғы 24 сағат    <span style='color:#59cfa2'>+0.8%</span>", "muted"))
        performance.addLayout(chart_heading)
        performance.addWidget(PerformanceChart())
        times = row()
        for index, time in enumerate(("00:00", "06:00", "12:00", "18:00", "24:00")):
            if index:
                times.addStretch()
            times.addWidget(label(time, "micro"))
        performance.addLayout(times)
        layout.addLayout(performance)
        self.engine_picker.currentIndexChanged.connect(self.select_engine)
        self.select_engine(0)
        return panel

    def select_engine(self, index):
        self.engine = ENGINES[index]
        self.engine_detail.setText(f"{self.engine.id} · {self.engine.kind}")
        self.diagram_title.setText(f"D I G I T A L   T W I N  /  {self.engine.id}")
        condition, health, summary = self.engine.assessment
        self.engine_condition.setText(condition)
        self.health_badge.setText(health)
        self.engine_health.setText(summary)
        states = ("↔ Тұрақты", "↔ Қалыпты", "↔ Тұрақты") if index == 0 else ("Демо мән",) * 3
        for reading, state, (caption, value, hint) in zip(self.engine.metrics, states, self.engine_metrics):
            caption.setText(reading.caption.upper())
            value.setText(f'{reading.number}<span style="font-size:12px;color:#8baac5"> {reading.unit}</span>')
            hint.setText(state)
        self.motor.set_engine(self.engine)
        if self.ai_reply is not None:
            reply, self.ai_reply = self.ai_reply, None
            reply.abort()
        self.ai_result.clear()
        self.ai_result.setPlaceholderText(f"{self.engine.id} демо көрсеткіштері бойынша қысқаша түсіндірме алыңыз.")
        self.ai_button.setEnabled(self.can_run)

    def show_sensor(self, index):
        reading = self.engine.sensors[index].reading
        self.sensor_name.setText(f"●  Датчик {chr(65 + index)}   ·   {reading.name}")
        self.sensor_value.setText(reading.value)

    def build_ai(self):
        panel = frame("aiPanel")
        panel.setFixedWidth(199)
        body = column(panel, (14, 15, 14, 15), 7)
        image = QPixmap(str(ASSETS / "smartdiagnost-ai-icon.png"))

        def ai_image(size):
            widget = QLabel()
            widget.setPixmap(image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            return widget

        heading = row(spacing=7)
        heading.addWidget(ai_image(30))
        titles = column(spacing=3)
        titles.addWidget(label("Жасанды интеллект"))
        titles.addWidget(label("ДИАГНОСТИКАЛЫҚ ТАЛДАУ", "micro"))
        heading.addLayout(titles, 1)
        body.addLayout(heading)
        body.addSpacing(5)
        model_name = "Gemma 4 26B · тегін" if self.ai_model == DEFAULT_AI_MODEL else self.ai_model
        model = label(model_name, "micro", wrap=True)
        model.setTextFormat(Qt.TextFormat.PlainText)
        model.setToolTip(self.ai_model)
        body.addWidget(model)
        body.addWidget(ai_image(72), 0, Qt.AlignmentFlag.AlignHCenter)
        body.addWidget(label("ДЕМО ДАТЧИКТЕРДІ ТАЛДАУ", "micro"))
        self.ai_result = QPlainTextEdit()
        self.ai_result.setObjectName("aiResult")
        self.ai_result.setAccessibleName("ЖИ талдауының нәтижесі")
        self.ai_result.setReadOnly(True)
        self.ai_result.setMinimumHeight(75)
        body.addWidget(self.ai_result, 1)
        self.ai_button = action_button("ЖИ талдау", "outline")
        self.ai_button.clicked.connect(self.request_ai_analysis)
        body.addWidget(self.ai_button)
        return panel

    def request_ai_analysis(self):
        if not self.can_run or not self.ai_button.isEnabled():
            return
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not key or not key.isascii() or not key.isprintable() or " " in key:
            self.ai_result.setPlainText("OPENROUTER_API_KEY мәнін PowerShell-де енгізіп, қолданбаны сол терезеден ашыңыз.")
            return

        engine = self.engine
        sensor_readings = [sensor.reading for sensor in engine.sensors]
        readings = dict.fromkeys(sensor_readings + list(engine.metrics))
        readings_text = "\n".join(f"{reading.name}: {reading.value}" for reading in readings)
        payload = {
            "model": self.ai_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "SmartDiagnost интерфейсі үшін қазақша 2–3 қысқа сөйлем жаз. "
                        "Тек берілген демо өлшемдерді түсіндір. Қалыпты диапазон берілмесе, "
                        "құрылғы күйін анықтама және сенімділік пайызын ойдан шығарма."
                    ),
                },
                {"role": "user", "content": f"{engine.id} · {engine.kind}. Демо өлшемдер:\n{readings_text}"},
            ],
            "stream": False,
            "max_tokens": 600,
        }
        request = QNetworkRequest(QUrl(OPENROUTER_URL))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setRawHeader(b"Authorization", b"Bearer " + key.encode("ascii"))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.SameOriginRedirectPolicy)
        request.setTransferTimeout(30_000)
        self.ai_result.setPlainText("OpenRouter жауабы күтілуде…")
        self.ai_button.setEnabled(False)
        self.ai_reply = self.ai_network.post(request, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def show_ai_result(self, reply):
        if reply != self.ai_reply:
            reply.deleteLater()
            return
        self.ai_reply = None
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        error = reply.error()
        raw = bytes(reply.readAll())
        reply.deleteLater()
        self.ai_button.setEnabled(self.can_run)

        if status is not None and not 200 <= status < 300:
            result = AI_ERRORS.get(status, f"OpenRouter қатесі (HTTP {status}).")
        elif error in (QNetworkReply.NetworkError.TimeoutError, QNetworkReply.NetworkError.OperationCanceledError):
            result = "OpenRouter жауабы уақытында келмеді. Қайталап көріңіз."
        elif error != QNetworkReply.NetworkError.NoError:
            result = "OpenRouter-ге қосылу мүмкін болмады. Интернет байланысын тексеріңіз."
        else:
            try:
                content = json.loads(raw)["choices"][0]["message"]["content"]
                result = content.strip() if isinstance(content, str) else ""
            except (ValueError, KeyError, IndexError, TypeError):
                result = ""
            if not result:
                result = "OpenRouter бос немесе жарамсыз жауап қайтарды. Қайталап көріңіз."
        self.ai_result.setPlainText(result)

    # ------------------------------------------------------------------ new check (now database-backed)
    def build_new_check(self):
        panel, layout = make_panel("Жаңа тексеріс", "NEW DIAGNOSTIC SESSION", ctx=self.ctx, technical=True)
        panel.setMinimumHeight(380)
        body = column(margins=(19, 16, 19, 19), spacing=10)
        self.device = QLineEdit(placeholderText="Мысалы, Bosch GBH 2-28 F")
        self.model = QLineEdit(placeholderText="Hammer Drill")
        self.category = QComboBox()
        self.category.addItems(CATEGORIES)
        self.entry_id = QLineEdit(placeholderText="Автоматты")
        self.entry_id.setMinimumWidth(54)
        field(body, "Құрылғы атауы", self.device)
        field(body, "Модель", self.model)
        pair = row(spacing=8)
        category, identifier = column(spacing=8), column(spacing=8)
        field(category, "Санат", self.category)
        field(identifier, "Құрылғы ID", self.entry_id)
        self.category.setMinimumWidth(149)
        pair.addLayout(category, 3)
        pair.addLayout(identifier, 2)
        body.addLayout(pair)
        body.addSpacing(3)
        save = action_button("+  Тексерісті сақтау", "primary", 38)
        save.clicked.connect(self.create_entry)
        for editor in (self.device, self.model, self.entry_id):
            editor.returnPressed.connect(self.create_entry)
        body.addWidget(save)
        layout.addLayout(body)
        return panel

    def create_entry(self):
        try:
            record = self.ctx.services.history.register_check(
                self.ctx.user, device=self.device.text(), model=self.model.text(),
                category=self.category.currentText(), code=self.entry_id.text())
        except SmartDiagnostError as error:
            show_error(self, error)
            if not self.device.text().strip():
                self.device.setFocus()
            elif not self.model.text().strip():
                self.model.setFocus()
            return
        for editor in (self.device, self.model, self.entry_id):
            editor.clear()
        self.category.setCurrentIndex(0)
        self.ctx.equipment_changed.emit()
        self.ctx.history_changed.emit()
        self.runner.select_equipment(record.equipment_id)
        self.show_notice(
            f"Тексеріс {record.test_code} базаға сақталды. Жоғарыдағы тест панелінде диагностиканы іске қосыңыз.")

    # ------------------------------------------------------------------ preferences (unchanged behaviour)
    def build_preferences(self):
        panel, layout = make_panel("Баптаулар", "WORKSPACE PREFERENCES", ctx=self.ctx, technical=True, height=66)
        form = column(margins=(15, 14, 15, 16), spacing=8)
        self.language = QComboBox()
        self.language.addItems(("Қазақша / English", "Қазақша"))
        self.source = QComboBox()
        self.source.addItems(("Ішкі микрофон", "Сыртқы діріл датчигі"))
        field(form, "Интерфейс тілі", self.language)
        field(form, "Сигнал көзі", self.source)
        apply = action_button("Параметрлерді қолдану", "outline")
        apply.clicked.connect(self.apply_preferences)
        form.addWidget(apply)
        layout.addLayout(form)
        return panel

    def apply_preferences(self):
        self.recorder.set_vibration(self.source.currentIndex() == 1)
        bilingual = self.language.currentIndex() == 0
        self.ctx.set_bilingual(bilingual)
        language = "Екітілді техникалық атаулар көрсетіледі." if bilingual else "Интерфейс тілі — қазақша."
        self.show_notice(f"Сигнал көзі · {self.source.currentText()}. {language}")

    # ------------------------------------------------------------------ sections
    def show_section(self, section):
        engine, equipment, settings = section == ENGINE, section == EQUIPMENT, section == SETTINGS
        self.overview.setVisible(engine)
        self.runner.setVisible(equipment)
        self.new_check.setVisible(equipment and self.ctx.can(Perm.DIAG_EQUIPMENT) and self.can_run)
        self.record_panel.setVisible(engine or equipment)
        self.acquisition.setVisible(engine or equipment)
        self.acquisition.setFixedWidth(287 if engine else 390)
        self.preferences.setVisible(settings)
        self.preferences.setMaximumWidth(390)
        self.scroll.verticalScrollBar().setValue(0)
        if equipment and self.new_check.isVisible():
            self.device.setFocus()

    def show_notice(self, message):
        self.notice_text.setText(message)
        self.notice.show()
        self.scroll.verticalScrollBar().setValue(0)

    def shutdown(self):
        if self.ai_reply is not None:
            reply, self.ai_reply = self.ai_reply, None
            reply.abort()
        self.recorder.shutdown()
