"""Engineering lab (Engineer / Administrator): extended parameters, technical measurements, trends, technical reports."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHeaderView, QLabel, QScrollArea, QTableWidget, QTableWidgetItem, QWidget,
)

from desktop_visuals import column, label, row

from .. import diagnostics
from ..errors import SmartDiagnostError
from .common import Sparkline, fit_table, fmt_local, make_panel, page_header, show_error
from .test_runner import STATE_COLORS, STATE_GLYPHS, TestRunnerPanel, fmt


class LabPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.equipment_id = None
        outer = column(self)
        scroll = QScrollArea(widgetResizable=True)
        outer.addWidget(scroll)
        surface = QWidget()
        surface.setObjectName("surface")
        scroll.setWidget(surface)
        layout = column(surface, (24, 20, 24, 20), 16)
        layout.addWidget(page_header(
            "Инженерлік зертхана",
            "Кеңейтілген параметрлер, ескерту шегін реттеу, техникалық өлшемдер, тренд және техникалық есеп."))
        columns = row(spacing=16)
        layout.addLayout(columns)

        self.runner = TestRunnerPanel(ctx, advanced=True)
        columns.addWidget(self.runner, 3, Qt.AlignmentFlag.AlignTop)

        side = column(spacing=16)
        measurements, measurement_body = make_panel("Техникалық өлшемдер", "", "LAST TEST", height=66)
        self.measure_hint = measurements.findChild(QLabel, "muted")
        holder = column(margins=(16, 10, 16, 14), spacing=8)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ПАРАМЕТР", "МӘН", "ДИАПАЗОН", "КҮЙІ"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        holder.addWidget(self.table)
        self.no_data = label("Бұл жабдық үшін сақталған өлшем жоқ. Тест іске қосып, есепті сақтаңыз.", "muted", wrap=True)
        holder.addWidget(self.no_data)
        measurement_body.addLayout(holder)
        side.addWidget(measurements)

        trend, trend_body = make_panel("Параметр трендісі", None, "TREND", height=66)
        trend_holder = column(margins=(16, 12, 16, 14), spacing=8)
        self.param = QComboBox()
        self.param.setAccessibleName("Параметр")
        self.param.currentIndexChanged.connect(self.update_trend)
        trend_holder.addWidget(self.param)
        self.spark = Sparkline()
        trend_holder.addWidget(self.spark)
        trend_holder.addWidget(label("Көгілдір аймақ — нормалық диапазон; қызыл нүкте — диапазоннан тыс мән.", "micro", wrap=True))
        trend_body.addLayout(trend_holder)
        side.addWidget(trend)
        side.addStretch()
        columns.addLayout(side, 2)
        layout.addStretch()

        self.runner.equipment_selected.connect(self.select_equipment)
        ctx.history_changed.connect(self.refresh)
        self.select_equipment(self.runner.picker.currentData())

    def on_show(self):
        self.refresh()

    def select_equipment(self, equipment_id):
        self.equipment_id = equipment_id
        self.param.blockSignals(True)
        self.param.clear()
        for spec in self.runner.current_profile().specs(True):
            self.param.addItem(f"{spec.label}, {spec.unit}", spec)
        self.param.blockSignals(False)
        self.refresh()

    def refresh(self):
        if self.equipment_id is None:
            return
        try:
            records = self.ctx.services.history.trend(self.ctx.user, self.equipment_id)
        except SmartDiagnostError as error:
            show_error(self, error)
            return
        latest = records[-1] if records else None
        findings = latest.details.get("findings", []) if latest else []
        self.table.setRowCount(len(findings))
        for index, item in enumerate(findings):
            state = diagnostics.State(item["state"])
            cells = (item["label"], f"{fmt(item['value'])} {item['unit']}",
                     f"{fmt(item['low'])}–{fmt(item['high'])} {item['unit']}",
                     f"{STATE_GLYPHS[state]}  {diagnostics.STATE_LABELS[state]}")
            for col, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if col == 3:
                    cell.setForeground(QColor(STATE_COLORS[state]))
                self.table.setItem(index, col, cell)
        fit_table(self.table, len(findings), 32)
        self.table.setVisible(bool(findings))
        self.no_data.setVisible(not findings)
        self.measure_hint.setText(
            f"{latest.test_code} · {fmt_local(latest.performed_at)}" if latest else "Сақталған тест жоқ")
        self.update_trend()

    def update_trend(self, *_):
        spec = self.param.currentData()
        if spec is None or self.equipment_id is None:
            self.spark.set_data([])
            return
        try:
            records = self.ctx.services.history.trend(self.ctx.user, self.equipment_id)
        except SmartDiagnostError:
            self.spark.set_data([])
            return
        values = [r.parameters[spec.key] for r in records if spec.key in r.parameters]
        self.spark.set_data(values, spec.low, spec.high, spec.unit)
