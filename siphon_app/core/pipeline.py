"""
siphon_app/core/pipeline.py

The steps between "tables found" and "files saved": clean every table, describe what the
cleaning did, pick file names and call the right exporter. Nothing here knows about windows,
so the window code stays small and all of this is easy to test.
"""
from pathlib import Path
from urllib.parse import urlparse

from siphon_app.core.cleaner import CleanReport, clean_table
from siphon_app.core.exporter import (
    ExportError, export_csv, export_json, export_xlsx, free_path, safe_filename,
)
from siphon_app.core.models import Table

FORMATS = {"csv": "CSV", "xlsx": "Excel", "json": "JSON"}        # key -> what the button says
FORMAT_HINTS = {
    "csv": "One .csv file for each table.",
    "xlsx": "One Excel workbook, with a sheet for each table.",
    "json": "One .json file holding every table.",
}


def clean_all(tables: list[Table]) -> list[tuple[Table, CleanReport]]:
    """Clean every table. Slow on big tables (about 1.5 s for 30,000 rows), so run it on the worker."""
    return [clean_table(table) for table in tables]


def summarize(reports: list[CleanReport]) -> str:
    """One sentence about what cleaning did to all the tables together."""
    columns = sum(len(report.columns) for report in reports)
    if not columns:
        return "No number columns found, so nothing needed converting."
    cells = sum(report.cells_converted for report in reports)
    kept = sum(report.cells_kept_as_text for report in reports)
    text = f"Turned {cells:,} cells in {columns} {'column' if columns == 1 else 'columns'} into numbers."
    if kept:
        text += f" {kept:,} {'cell' if kept == 1 else 'cells'} didn't look like numbers and stayed as text."
    return text


def base_name(tables: list[Table]) -> str:
    """The file name (no extension) for a one-file export: the table's name, or the site's name."""
    if len(tables) == 1:
        return safe_filename(tables[0].name)
    host = urlparse(tables[0].source_url).hostname or ""
    return safe_filename(f"tables from {host}") if host else "tables"


def export_tables(tables: list[Table], fmt: str, folder: str) -> list[Path]:
    """Save the tables in the folder. Returns the files written. Never overwrites an existing file."""
    if not tables:
        raise ExportError("There are no tables to export.")
    if fmt not in FORMATS:
        raise ExportError(f"Unknown format: {fmt}.")
    if not folder.strip():
        raise ExportError("Choose a folder to save into.")
    target = Path(folder.strip()).expanduser()
    if fmt == "csv":
        return export_csv(tables, target)
    extension = f".{fmt}"
    path = free_path(target, base_name(tables), extension)
    writer = export_xlsx if fmt == "xlsx" else export_json
    return [writer(tables, path)]


def describe(paths: list[Path]) -> str:
    """'Saved prices.csv to C:\\Users\\me\\Downloads.' for the status bar."""
    if len(paths) == 1:
        return f"Saved {paths[0].name} to {paths[0].parent}."
    return f"Saved {len(paths)} files to {paths[0].parent}."