"""Report builders: TXT, CSV, HTML and PDF. All user-provided text is escaped."""
import csv
import html
import re
from pathlib import Path

from .config import APP_NAME
from .diagnostics import STATE_LABELS, State
from .models import HistoryRecord


def local_text(moment, fmt="%d.%m.%Y %H:%M"):
    return moment.astimezone().strftime(fmt)


def safe_filename(name: str) -> str:
    return re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_")[:80] or "report"


def _num(value, decimals=2):
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return text or "0"


def _findings(record: HistoryRecord):
    return record.details.get("findings") or []


def record_to_text(record: HistoryRecord, technical=False) -> str:
    title = "TECHNICAL REPORT" if technical else "DIAGNOSTIC REPORT"
    lines = [
        f"{APP_NAME} — {title}" + ("  [DEMO SAMPLE]" if record.is_demo else ""),
        f"Test ID:   {record.test_code}",
        f"Date:      {local_text(record.performed_at)}",
        f"Operator:  {record.operator}",
        f"Equipment: {record.equipment_name} ({record.equipment_code})",
        f"Model:     {record.equipment_model}",
        f"Category:  {record.category}",
        f"Status:    {record.status_label}",
        f"Result:    {record.result}",
    ]
    findings = _findings(record)
    if findings:
        lines += ["", "Parameters:"]
        for item in findings:
            state = STATE_LABELS[State(item["state"])]
            lines.append(
                f"  - {item['label']}: {_num(item['value'])} {item['unit']}"
                f"  (nominal {_num(item['low'])}–{_num(item['high'])}, {state})"
            )
        if "health" in record.details:
            lines.append(f"Health index: {record.details['health']}%")
        if technical:
            lines.append(f"Warning margin: {round(record.details.get('margin', 0.1) * 100)}% of nominal range")
    if record.notes:
        lines += ["", f"Notes: {record.notes}"]
    if record.is_demo:
        lines += ["", "Demonstration data only. Not a real diagnostic assessment."]
    return "\n".join(lines) + "\n"


_CSS = (
    "body{font-family:'Segoe UI',Arial,sans-serif;color:#17202b;font-size:10pt}"
    "h1{color:#0f4c81;font-size:17pt;margin-bottom:2px}h2{color:#0f4c81;font-size:12pt;margin-top:14px}"
    "table{border-collapse:collapse;width:100%}th{background:#e7eef6;text-align:left}"
    "td,th{border:1px solid #b9c7d6;padding:4px 6px}.muted{color:#5c6b7a}"
    ".ok{color:#157a4f}.warning{color:#a8650a}.critical{color:#b3263a}"
)


def record_to_html(record: HistoryRecord, technical=False) -> str:
    esc = html.escape
    rows = "".join(
        f"<tr><td>{esc(item['label'])}</td><td>{_num(item['value'])} {esc(item['unit'])}</td>"
        f"<td>{_num(item['low'])} – {_num(item['high'])} {esc(item['unit'])}</td>"
        f"<td>{item['deviation'] * 100:.1f}%</td>"
        f"<td class='{esc(item['state'])}'>{esc(STATE_LABELS[State(item['state'])])}</td></tr>"
        for item in _findings(record)
    )
    table = (
        "<h2>Параметрлер / Parameters</h2><table><tr><th>Параметр</th><th>Өлшенген мән</th>"
        "<th>Нормалық диапазон</th><th>Ауытқу</th><th>Күйі</th></tr>" + rows + "</table>"
    ) if rows else ""
    info = (
        ("Test ID", record.test_code), ("Күні / Date", local_text(record.performed_at)),
        ("Орындаушы / Operator", record.operator),
        ("Жабдық / Equipment", f"{record.equipment_name} ({record.equipment_code})"),
        ("Модель / Model", record.equipment_model), ("Санат / Category", record.category),
        ("Күйі / Status", record.status_label), ("Нәтиже / Result", record.result),
    )
    meta = "".join(f"<tr><th width='30%'>{esc(k)}</th><td>{esc(str(v))}</td></tr>" for k, v in info)
    extras = ""
    if "health" in record.details:
        extras += f"<p>Денсаулық индексі / Health index: <b>{int(record.details['health'])}%</b></p>"
    if technical:
        margin = round(record.details.get("margin", 0.1) * 100)
        extras += f"<p class='muted'>Ескерту шегі / Warning margin: {margin}% of nominal range. Ranges are illustrative defaults.</p>"
    if record.notes:
        extras += f"<h2>Ескертпелер / Notes</h2><p>{esc(record.notes)}</p>"
    if record.is_demo:
        extras += "<p class='muted'>Demonstration data only. Not a real diagnostic assessment.</p>"
    title = "Техникалық есеп" if technical else "Диагностика есебі"
    return (
        f"<html><head><meta charset='utf-8'><style>{_CSS}</style></head><body>"
        f"<h1>{esc(APP_NAME)}</h1><p class='muted'>{title}</p><table>{meta}</table>{table}{extras}</body></html>"
    )


def write_text(record, path, technical=False):
    Path(path).write_text(record_to_text(record, technical), encoding="utf-8")


def write_pdf(record, path, technical=False):
    """Render the HTML report to PDF with Qt (imported lazily so the core stays Qt-free)."""
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument

    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    document = QTextDocument()
    document.setHtml(record_to_html(record, technical))
    document.print_(writer)


def _csv_cell(value):
    text = "" if value is None else str(value)
    # Neutralise spreadsheet formula injection (=, +, -, @ at the start of a cell).
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def write_csv(records, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["Test ID", "Date", "Operator", "Equipment", "Equipment ID", "Model", "Category", "Status",
                         "Result", "Parameters", "Notes"])
        for r in records:
            params = "; ".join(f"{item['label']}={_num(item['value'])} {item['unit']}" for item in _findings(r))
            writer.writerow([_csv_cell(v) for v in (
                r.test_code, local_text(r.performed_at, "%Y-%m-%d %H:%M"), r.operator, r.equipment_name,
                r.equipment_code, r.equipment_model, r.category, r.status_label, r.result, params, r.notes)])
