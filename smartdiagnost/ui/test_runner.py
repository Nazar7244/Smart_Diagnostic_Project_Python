"""Diagnostic test panel: choose equipment, enter measured values, run the rules, save the report."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QGridLayout, QHeaderView, QLineEdit, QSpinBox, QTableWidget,
    QTableWidgetItem, QWidget,
)
from PySide6.QtGui import QColor

from desktop_visuals import column, frame, label, row

from .. import diagnostics
from ..errors import SmartDiagnostError
from ..models import HistoryRecord, utc_now
from ..permissions import Perm
from .common import (
    action_button, fit_table, make_panel, set_badge, show_error, status_badge,
)
from .exports import export_record

STATE_COLORS = {
    diagnostics.State.OK: "#59cfa2", diagnostics.State.WARNING: "#f4ba77", diagnostics.State.CRITICAL: "#f2788a",
}
STATE_GLYPHS = {diagnostics.State.OK: "✓", diagnostics.State.WARNING: "!", diagnostics.State.CRITICAL: "✕"}


def fmt(value, decimals=2):
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".") if decimals else f"{value:.0f}"


class TestRunnerPanel(QWidget):
    saved = Signal(object)
    equipment_selected = Signal(int)

    def __init__(self, ctx, advanced=False):
        super().__init__()
        self.ctx = ctx
        self.advanced = advanced and ctx.can(Perm.DIAG_ADVANCED)
        self.spinners = {}
        self.outcome = None
        self.saved_record = None
        self.equipment = []

        outer = column(self)
        title = "Кеңейтілген диагностика" if self.advanced else "Диагностикалық тест"
        subtitle = "ADVANCED EQUIPMENT TEST" if self.advanced else "RUN DIAGNOSTIC TEST"
        self.card, body = make_panel(title, subtitle, ctx=ctx, technical=True, height=66)
        outer.addWidget(self.card)

        form = column(margins=(19, 16, 19, 18), spacing=8)
        body.addLayout(form)
        self.picker = QComboBox()
        self.picker.setAccessibleName("Жабдықты таңдау")
        form.addWidget(label("Жабдық", "muted"))
        form.addWidget(self.picker)
        self.profile_hint = label("", "micro", wrap=True)
        form.addWidget(self.profile_hint)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 4, 0, 4)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(7)
        self.grid.setColumnStretch(0, 1)
        form.addWidget(self.grid_host)

        self.margin = QSpinBox()
        self.margin.setRange(1, 50)
        self.margin.setValue(int(diagnostics.DEFAULT_MARGIN * 100))
        self.margin.setSuffix(" %")
        self.margin.setAccessibleName("Ескерту шегі")
        self.margin_row = QWidget()
        margin_layout = row(self.margin_row, spacing=10)
        margin_layout.addWidget(label("Ескерту шегі (диапазон ауқымынан)", "muted"), 1)
        margin_layout.addWidget(self.margin)
        self.margin_row.setVisible(self.advanced)
        form.addWidget(self.margin_row)

        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Ескертпе (міндетті емес)")
        self.notes.setMaxLength(500)
        self.notes.setAccessibleName("Ескертпе")
        form.addWidget(self.notes)

        buttons = row(spacing=8)
        self.run = action_button("▶  Тестті іске қосу", "primary", 40)
        self.run.clicked.connect(self.run_test)
        self.reset = action_button("Бастапқы мәндер", "outline", 40)
        self.reset.clicked.connect(self.reset_values)
        buttons.addWidget(self.run, 1)
        buttons.addWidget(self.reset)
        form.addLayout(buttons)

        self.result = frame("readout")
        self.result.setMinimumHeight(0)
        result_layout = column(self.result, (14, 12, 14, 12), 8)
        head = row(spacing=10)
        self.badge = status_badge("pending")
        self.health = label("", "accent")
        head.addWidget(self.badge)
        head.addWidget(self.health)
        head.addStretch()
        result_layout.addLayout(head)
        self.summary = label("", "", wrap=True)
        result_layout.addWidget(self.summary)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ПАРАМЕТР", "МӘН", "ДИАПАЗОН", "АУЫТҚУ", "КҮЙІ"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setDefaultSectionSize(34)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        result_layout.addWidget(self.table)
        actions = row(spacing=8)
        self.save = action_button("Есепті сақтау", "outline", 38)
        self.save.clicked.connect(self.save_report)
        self.export = action_button("↓  Есепті жүктеу", "outline", 38)
        self.export.clicked.connect(self.export_report)
        actions.addWidget(self.save, 1)
        actions.addWidget(self.export, 1)
        result_layout.addLayout(actions)
        form.addWidget(self.result)
        self.result.hide()

        self.status = label("", "accent", wrap=True)
        form.addWidget(self.status)

        self.denied = not ctx.can(Perm.DIAG_RUN)
        if self.denied:
            self.status.setText("Демо режим: диагностика тестін іске қосу үшін Механик, Инженер немесе Әкімші рөлі қажет.")
            for widget in (self.picker, self.grid_host, self.run, self.reset, self.notes, self.margin):
                widget.setEnabled(False)
        self.picker.currentIndexChanged.connect(self.on_equipment_changed)
        ctx.equipment_changed.connect(self.reload_equipment)
        self.reload_equipment()

    # ------------------------------------------------------------------ equipment & inputs
    def reload_equipment(self):
        current = self.picker.currentData()
        self.picker.blockSignals(True)
        self.equipment = self.ctx.services.equipment.list()
        self.picker.clear()
        for item in self.equipment:
            self.picker.addItem(f"{item.label}  ({item.code})", item.id)
        index = self.picker.findData(current) if current is not None else 0
        self.picker.setCurrentIndex(max(index, 0))
        self.picker.blockSignals(False)
        self.on_equipment_changed()

    def select_equipment(self, equipment_id):
        index = self.picker.findData(equipment_id)
        if index >= 0:
            self.picker.setCurrentIndex(index)

    def current_equipment(self):
        data = self.picker.currentData()
        return next((item for item in self.equipment if item.id == data), None)

    def current_profile(self):
        item = self.current_equipment()
        return diagnostics.profile_for(item.profile if item else "", item.category if item else "")

    def on_equipment_changed(self, *_):
        while self.grid.count():
            widget = self.grid.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        self.spinners.clear()
        profile = self.current_profile()
        item = self.current_equipment()
        self.profile_hint.setText(f"Профиль: {profile.title} · Нормалық диапазондар — демо әдепкі мәндер, өндіруші спецификациясы емес.")
        for index, spec in enumerate(profile.specs(self.advanced)):
            spin = QDoubleSpinBox()
            spin.setDecimals(spec.decimals)
            spin.setRange(-100000.0, 10000000.0)
            spin.setSingleStep(10 ** -spec.decimals if spec.decimals else 1)
            spin.setValue(spec.default)
            spin.setKeyboardTracking(False)
            spin.setAccessibleName(spec.label)
            spin.setMinimumWidth(110)
            spin.setEnabled(not self.denied)
            spin.valueChanged.connect(self.invalidate)
            self.spinners[spec.key] = spin
            self.grid.addWidget(label(spec.label, ""), index, 0)
            self.grid.addWidget(spin, index, 1)
            self.grid.addWidget(label(spec.unit, "muted"), index, 2)
            self.grid.addWidget(label(f"{fmt(spec.low)}–{fmt(spec.high)}", "micro"), index, 3)
        self.invalidate()
        if item:
            self.equipment_selected.emit(item.id)

    def reset_values(self):
        for spec in self.current_profile().specs(self.advanced):
            self.spinners[spec.key].setValue(spec.default)
        self.margin.setValue(int(diagnostics.DEFAULT_MARGIN * 100))

    def values(self):
        return {key: spin.value() for key, spin in self.spinners.items()}

    def invalidate(self, *_):
        self.outcome = None
        self.saved_record = None
        self.result.hide()
        self.status.setText("" if not self.denied else self.status.text())

    # ------------------------------------------------------------------ run / save / export
    def margin_value(self):
        return self.margin.value() / 100 if self.advanced else diagnostics.DEFAULT_MARGIN

    def run_test(self):
        item = self.current_equipment()
        if item is None:
            return
        try:
            profile, outcome = self.ctx.services.history.evaluate(
                self.ctx.user, item.id, self.values(), self.margin_value(), self.advanced)
        except SmartDiagnostError as error:
            show_error(self, error)
            return
        self.outcome, self.saved_record = outcome, None
        set_badge(self.badge, outcome.status)
        self.health.setText(f"Денсаулық индексі {outcome.health}%")
        self.summary.setText(outcome.summary)
        self.table.setRowCount(len(outcome.findings))
        for index, finding in enumerate(outcome.findings):
            color = QColor(STATE_COLORS[finding.state])
            cells = (
                finding.label, f"{fmt(finding.value)} {finding.unit}",
                f"{fmt(finding.low)}–{fmt(finding.high)} {finding.unit}", f"{finding.deviation * 100:.1f}%",
                f"{STATE_GLYPHS[finding.state]}  {diagnostics.STATE_LABELS[finding.state]}",
            )
            for col, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                cell.setToolTip(finding.message)
                if col == 4:
                    cell.setForeground(color)
                self.table.setItem(index, col, cell)
        fit_table(self.table, len(outcome.findings))
        self.save.setEnabled(self.ctx.can(Perm.REPORT_SAVE))
        self.save.setText("Есепті сақтау")
        self.export.setVisible(self.ctx.can(Perm.REPORT_EXPORT))
        self.result.show()
        self.status.setText("")

    def save_report(self):
        item = self.current_equipment()
        if item is None or self.outcome is None:
            return
        try:
            record = self.ctx.services.history.save_test(
                self.ctx.user, item.id, self.values(), self.margin_value(), self.advanced, self.notes.text())
        except SmartDiagnostError as error:
            show_error(self, error)
            return
        self.saved_record = record
        self.save.setEnabled(False)
        self.save.setText("✓  Сақталды")
        self.status.setText(f"Есеп сақталды: {record.test_code}. Диагностика тарихынан көре аласыз.")
        self.ctx.history_changed.emit()
        self.saved.emit(record)

    def current_record(self) -> HistoryRecord | None:
        """The saved record if there is one, else a transient (unsaved) record for the last run."""
        if self.saved_record is not None:
            return self.saved_record
        item = self.current_equipment()
        if item is None or self.outcome is None:
            return None
        user, profile = self.ctx.user, self.current_profile()
        details = dict(self.outcome.as_dict(), profile=profile.key, advanced=self.advanced, margin=self.margin_value())
        return HistoryRecord(
            id=0, test_code="(сақталмаған)", user_id=user.id, operator=user.full_name, equipment_id=item.id,
            equipment_code=item.code, equipment_name=item.name, equipment_model=item.model, category=item.category,
            performed_at=utc_now(), parameters=self.values(), result=self.outcome.summary, details=details,
            status=self.outcome.status, notes=self.notes.text().strip(),
        )

    def export_report(self):
        record = self.current_record()
        if record is not None:
            export_record(self, record, technical=self.advanced and self.ctx.can(Perm.REPORT_TECHNICAL))
