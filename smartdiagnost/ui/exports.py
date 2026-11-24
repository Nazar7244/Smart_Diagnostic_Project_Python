"""File-dialog front ends for the report builders."""
from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from .. import reports
from .common import show_error, show_info

PDF_FILTER, TXT_FILTER, CSV_FILTER = "PDF есеп (*.pdf)", "Мәтіндік есеп (*.txt)", "CSV кесте (*.csv)"


def export_record(parent, record, technical=False) -> bool:
    """Ask for a destination and write one report as PDF or TXT. Returns True when a file was written."""
    prefix = "TECH_" if technical else ""
    default = f"{prefix}{reports.safe_filename(record.test_code)}.pdf"
    path, chosen = QFileDialog.getSaveFileName(
        parent, "Есепті сақтау", default, f"{PDF_FILTER};;{TXT_FILTER}")
    if not path:
        return False
    target = Path(path)
    as_text = target.suffix.lower() == ".txt" or (not target.suffix and chosen == TXT_FILTER)
    if not target.suffix:
        target = target.with_suffix(".txt" if as_text else ".pdf")
    try:
        (reports.write_text if as_text else reports.write_pdf)(record, target, technical)
    except Exception:  # noqa: BLE001 - disk/permission/Qt print failures all mean "could not save"
        show_error(parent, "Есепті сақтау мүмкін болмады. Файл жолын тексеріңіз.")
        return False
    show_info(parent, f"Есеп сақталды:\n{target}")
    return True


def export_csv(parent, records) -> bool:
    if not records:
        show_info(parent, "Экспорттауға жазба жоқ.")
        return False
    path, _ = QFileDialog.getSaveFileName(parent, "Тарихты экспорттау", "smartdiagnost_history.csv", CSV_FILTER)
    if not path:
        return False
    target = Path(path)
    if not target.suffix:
        target = target.with_suffix(".csv")
    try:
        reports.write_csv(records, target)
    except OSError:
        show_error(parent, "CSV файлын сақтау мүмкін болмады. Файл жолын тексеріңіз.")
        return False
    show_info(parent, f"{len(records)} жазба экспортталды:\n{target}")
    return True
