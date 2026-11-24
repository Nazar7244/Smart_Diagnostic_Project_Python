"""Database-backed diagnostic history: search, filter, view, edit, delete and export."""
from PySide6.QtCore import QDate, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QGridLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
    QTableWidget, QTableWidgetItem, QToolButton, QWidget,
)

from desktop_visuals import column, frame, icon, label, row

from ..diagnostics import STATE_LABELS, State
from ..errors import SmartDiagnostError
from ..models import STATUS_LABELS, STATUSES
from ..permissions import Perm
from .common import (
    STATUS_COLORS, STATUS_GLYPHS, action_button, confirm, fit_table, fmt_local, make_panel, page_header, show_error,
    status_badge,
)
from .exports import export_csv, export_record
from .test_runner import STATE_COLORS, fmt

MIN_DATE = QDate(2000, 1, 1)


class RecordDialog(QDialog):
    """Read-only view of one diagnostic report."""

    def __init__(self, ctx, record, parent=None):
        super().__init__(parent)
        self.ctx, self.record = ctx, record
        self.setObjectName("authDialog")
        self.setWindowTitle(f"Диагностика · {record.test_code}")
        self.setMinimumWidth(640)
        layout = column(self, (26, 22, 26, 20), 10)
        head = row(spacing=12)
        head.addWidget(label(record.test_code, "authTitle"))
        head.addWidget(status_badge(record.status))
        if record.is_demo:
            head.addWidget(label("DEMO", "tag"))
        head.addStretch()
        layout.addLayout(head)
        layout.addWidget(label(record.result or "—", "accent", wrap=True))

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(6)
        info = (
            ("Жабдық", f"{record.equipment_name} ({record.equipment_code})"), ("Модель", record.equipment_model or "—"),
            ("Санат", record.category), ("Орындаушы", record.operator),
            ("Күні", fmt_local(record.performed_at, "dd.MM.yyyy HH:mm")),
            ("Денсаулық индексі", f"{record.details['health']}%" if "health" in record.details else "—"),
        )
        for index, (caption, value) in enumerate(info):
            cell = column(spacing=2)
            cell.addWidget(label(caption.upper(), "micro"))
            text = label(value, "")
            text.setTextFormat(Qt.TextFormat.PlainText)
            text.setWordWrap(True)
            cell.addWidget(text)
            grid.addLayout(cell, index // 2, index % 2)
        layout.addLayout(grid)

        findings = record.details.get("findings") or []
        if findings:
            layout.addWidget(label("ПАРАМЕТРЛЕР", "micro"))
            table = QTableWidget(len(findings), 4)
            table.setHorizontalHeaderLabels(["ПАРАМЕТР", "МӘН", "ДИАПАЗОН", "КҮЙІ"])
            table.verticalHeader().hide()
            table.setShowGrid(False)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            table.verticalHeader().setDefaultSectionSize(32)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            for r, item in enumerate(findings):
                state = State(item["state"])
                cells = (item["label"], f"{fmt(item['value'])} {item['unit']}",
                         f"{fmt(item['low'])}–{fmt(item['high'])} {item['unit']}", STATE_LABELS[state])
                for c, text in enumerate(cells):
                    cell = QTableWidgetItem(text)
                    cell.setToolTip(item.get("message", ""))
                    if c == 3:
                        cell.setForeground(QColor(STATE_COLORS[state]))
                    table.setItem(r, c, cell)
            fit_table(table, len(findings), 32)
            layout.addWidget(table)
        elif record.status == "pending":
            layout.addWidget(label("Бұл тексеріс сигнал мен өлшемдерді күтуде. Диагностика тесті әлі іске қосылмаған.", "muted", wrap=True))
        if record.notes:
            layout.addWidget(label("ЕСКЕРТПЕ", "micro"))
            notes = label(record.notes, "", wrap=True)
            notes.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(notes)

        buttons = row(spacing=8)
        if ctx.can(Perm.REPORT_EXPORT):
            export = action_button("↓  Есеп (PDF / TXT)", "outline", 38)
            export.clicked.connect(lambda: export_record(self, record))
            buttons.addWidget(export)
            if ctx.can(Perm.REPORT_TECHNICAL) and findings:
                technical = action_button("Техникалық есеп", "outline", 38)
                technical.clicked.connect(lambda: export_record(self, record, technical=True))
                buttons.addWidget(technical)
        buttons.addStretch()
        close = action_button("Жабу", "primary", 38)
        close.setMinimumWidth(110)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addSpacing(6)
        layout.addLayout(buttons)


class EditRecordDialog(QDialog):
    def __init__(self, ctx, record, parent=None):
        super().__init__(parent)
        self.ctx, self.record = ctx, record
        self.setObjectName("authDialog")
        self.setWindowTitle(f"Жазбаны өңдеу · {record.test_code}")
        self.setMinimumWidth(460)
        equipment = ctx.services.equipment.get(record.equipment_id)
        self.can_rename = ctx.services.equipment.can_rename(ctx.user, equipment)
        layout = column(self, (26, 22, 26, 20), 8)
        layout.addWidget(label("Жазбаны өңдеу", "authTitle"))
        self.name = QLineEdit(record.equipment_name)
        self.model = QLineEdit(record.equipment_model)
        self.name.setMaxLength(80)
        self.model.setMaxLength(80)
        for caption, widget in (("Құрылғы", self.name), ("Модель", self.model)):
            heading = label(caption, "muted")
            heading.setBuddy(widget)
            layout.addWidget(heading)
            layout.addWidget(widget)
            widget.setEnabled(self.can_rename)
        if not self.can_rename:
            layout.addWidget(label(
                "Жабдық атауын тек оны тіркеген пайдаланушы немесе әкімші өзгерте алады.", "micro", wrap=True))
        heading = label("Ескертпе", "muted")
        layout.addWidget(heading)
        self.notes = QPlainTextEdit(record.notes)
        self.notes.setMaximumHeight(100)
        self.notes.setAccessibleName("Ескертпе")
        heading.setBuddy(self.notes)
        layout.addWidget(self.notes)
        buttons = row(spacing=8)
        cancel = action_button("Бас тарту", "outline", 38)
        cancel.clicked.connect(self.reject)
        save = action_button("Өзгерістерді сақтау", "primary", 38)
        save.clicked.connect(self.save)
        buttons.addWidget(cancel)
        buttons.addWidget(save, 1)
        layout.addSpacing(6)
        layout.addLayout(buttons)

    def save(self):
        try:
            self.ctx.services.history.update(
                self.ctx.user, self.record.id, notes=self.notes.toPlainText(),
                name=self.name.text() if self.can_rename else None,
                model=self.model.text() if self.can_rename else None)
        except SmartDiagnostError as error:
            show_error(self, error)
            return
        self.accept()


class HistoryPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.records = []
        self.scope = ctx.services.history.scope(ctx.user)
        self.can_export = ctx.can(Perm.REPORT_EXPORT)
        self.search_timer = QTimer(self, singleShot=True, interval=200)
        self.search_timer.timeout.connect(self.refresh)

        outer = column(self, (24, 20, 24, 17), 14)
        subtitle = {
            "all": "Барлық пайдаланушылардың диагностика есептері.",
            "own": "Сіз орындаған диагностикалар.",
            "demo": "Үлгі диагностика нәтижелері (демо режим, тек көру).",
        }[self.scope]
        outer.addWidget(page_header("Диагностика тарихы", subtitle))

        self.panel, body = make_panel("Жазбалар", "", "HISTORY", height=66)
        self.count = self.panel.findChild(QLabel, "muted")
        outer.addWidget(self.panel, 1)

        filters = row(margins=(16, 12, 16, 8), spacing=8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Құрылғы, модель, ID, орындаушы іздеу…")
        self.search.setAccessibleName("Диагностика тарихынан іздеу")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(38)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        self.status = QComboBox()
        self.status.setAccessibleName("Күй сүзгісі")
        self.status.addItem("Барлық күй", None)
        for key in STATUSES:
            self.status.addItem(f"{STATUS_GLYPHS[key]}  {STATUS_LABELS[key]}", key)
        self.status.currentIndexChanged.connect(self.refresh)
        self.operator = QComboBox()
        self.operator.setAccessibleName("Орындаушы сүзгісі")
        self.operator_filter = self.scope == "all" and ctx.can(Perm.USERS_MANAGE)
        self.operator.setVisible(self.operator_filter)
        self.operator.currentIndexChanged.connect(self.refresh)
        self.date_from, self.date_to = self._date_edit("Басталу күні"), self._date_edit("Аяқталу күні")
        reset = action_button("Тазарту", "outline", 38)
        reset.clicked.connect(self.reset_filters)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.status)
        filters.addWidget(self.operator)
        filters.addWidget(label("Мерзім", "muted"))
        filters.addWidget(self.date_from)
        filters.addWidget(label("–", "muted"))
        filters.addWidget(self.date_to)
        filters.addWidget(reset)
        if self.can_export:
            export = action_button("↓  CSV", "outline", 38)
            export.setToolTip("Сүзілген тізімді CSV файлына экспорттау")
            export.clicked.connect(lambda: export_csv(self, self.records))
            filters.addWidget(export)
        body.addLayout(filters)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["ТЕСТ ID", "ОРЫНДАУШЫ", "ЖАБДЫҚ / МОДЕЛЬ", "КҮНІ", "НӘТИЖЕ", "КҮЙІ", "ӘРЕКЕТТЕР"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(53)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(260)
        self.table.doubleClicked.connect(lambda index: self.view(self.records[index.row()]))
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(6, 232 if self.scope != "demo" else 90)
        self.table.setColumnHidden(1, self.scope != "all")
        body.addWidget(self.table, 1)
        self.empty = label("Жазба табылмады.", "muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setMinimumHeight(80)
        body.addWidget(self.empty)

        ctx.history_changed.connect(self.refresh)
        ctx.users_changed.connect(self.reload_operators)
        self.reload_operators()
        self.refresh()

    @staticmethod
    def _date_edit(name):
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("dd.MM.yyyy")
        edit.setMinimumDate(MIN_DATE)
        edit.setSpecialValueText("Барлығы")
        edit.setDate(MIN_DATE)
        edit.setAccessibleName(name)
        edit.setMinimumHeight(38)
        edit.setMinimumWidth(112)
        return edit

    def reload_operators(self):
        if not self.operator_filter:
            return
        with QSignalBlocker(self.operator):
            current = self.operator.currentData()
            self.operator.clear()
            self.operator.addItem("Барлық орындаушы", None)
            for user in self.ctx.services.users.list(self.ctx.user):
                self.operator.addItem(user.full_name, user.id)
            index = self.operator.findData(current)
            self.operator.setCurrentIndex(max(index, 0))

    def set_search(self, text):
        with QSignalBlocker(self.search):
            self.search.setText(text)
        self.refresh()

    def reset_filters(self):
        with QSignalBlocker(self.status), QSignalBlocker(self.operator), QSignalBlocker(self.search):
            self.search.clear()
            self.status.setCurrentIndex(0)
            self.operator.setCurrentIndex(0)
            self.date_from.setDate(MIN_DATE)
            self.date_to.setDate(MIN_DATE)
        self.refresh()

    def on_show(self):
        self.refresh()

    def refresh(self):
        date_from = self.date_from.date().toPython() if self.date_from.date() > MIN_DATE else None
        date_to = self.date_to.date().toPython() if self.date_to.date() > MIN_DATE else None
        try:
            self.records = self.ctx.services.history.search(
                self.ctx.user, text=self.search.text(), status=self.status.currentData(),
                operator_id=self.operator.currentData() if self.operator_filter else None,
                date_from=date_from, date_to=date_to)
        except SmartDiagnostError as error:
            show_error(self, error)
            return
        total = self.ctx.services.history.counts(self.ctx.user)["total"]
        self.count.setText(f"{len(self.records)} / {total} тексеріс")
        self.table.setRowCount(len(self.records))
        for index, record in enumerate(self.records):
            self.populate_row(index, record)
        self.table.setVisible(bool(self.records))
        self.empty.setVisible(not self.records)

    def populate_row(self, index, record):
        status_text = f"{STATUS_GLYPHS[record.status]}  {STATUS_LABELS[record.status]}"
        cells = (
            record.test_code + ("\nDEMO" if record.is_demo else ""), record.operator,
            f"{record.equipment_name}\n{record.equipment_model}", fmt_local(record.performed_at, "dd.MM.yyyy\nHH:mm"),
            record.result, status_text,
        )
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            if col == 5:
                item.setForeground(QColor(STATUS_COLORS[record.status]))
            self.table.setItem(index, col, item)
        actions = QWidget()
        buttons = row(actions, (2, 0, 2, 0), 4)
        specs = [("Қарау", "Есепті қарау", self.view)]
        if self.can_export:
            specs.append(("↓ Есеп", "Есепті жүктеу (PDF / TXT)", lambda rec: export_record(self, rec)))
        if self.ctx.services.history.can_modify(self.ctx.user, record):
            specs += [("Өңдеу", "Жазбаны өңдеу", self.edit), ("×", "Жазбаны жою", self.delete)]
        for text, tooltip, callback in specs:
            button = QToolButton(text=text, toolTip=tooltip, accessibleName=tooltip)
            button.setObjectName("tableAction")
            button.clicked.connect(lambda checked=False, action=callback, rec=record: action(rec))
            buttons.addWidget(button)
        buttons.addStretch()
        self.table.setCellWidget(index, 6, actions)

    # ------------------------------------------------------------------ row actions
    def view(self, record):
        try:
            fresh = self.ctx.services.history.get(self.ctx.user, record.id)
        except SmartDiagnostError as error:
            show_error(self, error)
            self.refresh()
            return
        RecordDialog(self.ctx, fresh, self).exec()

    def edit(self, record):
        if EditRecordDialog(self.ctx, record, self).exec() == QDialog.DialogCode.Accepted:
            self.ctx.equipment_changed.emit()
            self.ctx.history_changed.emit()

    def delete(self, record):
        if not confirm(self, f"{record.test_code} жазбасын жою керек пе? Бұл әрекетті қайтару мүмкін емес.", "Жою"):
            return
        try:
            self.ctx.services.history.delete(self.ctx.user, record.id)
        except SmartDiagnostError as error:
            show_error(self, error)
        self.ctx.history_changed.emit()
