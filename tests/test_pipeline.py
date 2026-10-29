"""Tests for siphon_app/core/pipeline.py. Nothing here needs a screen."""
import csv
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from siphon_app.core.cleaner import CleanReport, ColumnReport
from siphon_app.core.exporter import ExportError
from siphon_app.core.models import Table
from siphon_app.core.pipeline import (
    FORMATS, base_name, clean_all, describe, export_tables, summarize,
)

def table(name="Prices", rows=(("Alpha", "$1,234"), ("Beta", "$5")), url="https://example.com/p"):
    return Table(name, ["Name", "Price"], [list(r) for r in rows], source_url=url)

#cleaning
def test_clean_all_returns_a_cleaned_copy_and_a_report_for_each_table():
    original = table()
    result = clean_all([original, table("Other")])
    assert len(result) == 2
    cleaned, report = result[0]
    assert cleaned.rows == [["Alpha", 1234], ["Beta", 5]]
    assert report.cells_converted == 2
    assert original.rows[0][1] == "$1,234" # the original is untouched

def test_clean_all_of_nothing_is_nothing():
    assert clean_all([]) == []

def report(columns=0, converted=0, kept=0):
    return CleanReport([ColumnReport(name=f"c{i}", converted=converted // max(columns, 1),
                                    kept_as_text=kept if i == 0 else 0) for i in range(columns)])

def test_summarize_with_no_number_columns():
    assert summarize([]) == "No number columns found, so nothing needed converting."
    assert summarize([CleanReport(), CleanReport()]) == "No number columns found, so nothing needed converting."

def test_summarize_counts_across_all_tables_and_uses_the_right_plurals():
    assert summarize([report(1, 1)]) == "Turned 1 cells in 1 column into numbers."
    assert summarize([report(2, 2000), report(1, 1000)]) == "Turned 3,000 cells in 3 columns into numbers."

def test_summarize_mentions_cells_that_stayed_as_text():
    assert summarize([report(1, 10, kept=1)]).endswith("1 cell didn't look like numbers and stayed as text.")
    assert "12 cells didn't look like numbers" in summarize([report(1, 10, kept=12)])

#names
def test_base_name_for_one_table_is_its_name_made_safe():
    assert base_name([table("Population: 2020/21?")]) == "Population 2020 21"


def test_base_name_for_several_tables_is_the_site():
    assert base_name([table("A"), table("B")]) == "tables from example.com"

def test_base_name_without_a_site_falls_back():
    assert base_name([table("A", url=""), table("B", url="")]) == "tables"
    assert base_name([table("A", url="not a url"), table("B")]) == "tables" # no site name in it

#exporting
def test_csv_writes_one_file_per_table(tmp_path):
    paths = export_tables([table("One"), table("Two")], "csv", str(tmp_path))
    assert sorted(p.name for p in paths) == ["One.csv", "Two.csv"]
    with open(paths[0], encoding="utf-8-sig", newline="") as handle:
        assert list(csv.reader(handle)) == [["Name", "Price"], ["Alpha", "$1,234"], ["Beta", "$5"]]

def test_xlsx_writes_one_workbook_named_after_the_site(tmp_path):
    cleaned = [c for c, _ in clean_all([table("One"), table("Two")])]
    [path] = export_tables(cleaned, "xlsx", str(tmp_path))
    assert path.name == "tables from example.com.xlsx"
    book = load_workbook(path)
    assert book.sheetnames == ["One", "Two"]
    assert book["One"]["B2"].value == 1234                    # a real number, not "$1,234"

def test_a_single_table_gets_its_own_name_in_xlsx_and_json(tmp_path):
    [xlsx] = export_tables([table("Prices")], "xlsx", str(tmp_path))
    [js] = export_tables([table("Prices")], "json", str(tmp_path))
    assert (xlsx.name, js.name) == ("Prices.xlsx", "Prices.json")
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["tables"][0]["rows"][0] == {"Name": "Alpha", "Price": "$1,234"}

@pytest.mark.parametrize("fmt, first, second", [
    ("csv", "Prices.csv", "Prices (2).csv"),
    ("xlsx", "Prices.xlsx", "Prices (2).xlsx"),
    ("json", "Prices.json", "Prices (2).json"),
])
def test_exporting_twice_never_overwrites_the_first_file(tmp_path, fmt, first, second):
    [one] = export_tables([table()], fmt, str(tmp_path))
    before = one.read_bytes()
    [two] = export_tables([table(rows=[("Other", "9")])], fmt, str(tmp_path))
    assert (one.name, two.name) == (first, second)
    assert one.read_bytes() == before

def test_the_folder_is_created_if_it_does_not_exist(tmp_path):
    target = tmp_path / "new" / "deeper"
    [path] = export_tables([table()], "json", str(target))
    assert path.parent == target and path.exists()

def test_a_home_folder_shortcut_is_understood(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    [path] = export_tables([table()], "json", "~/out")
    assert path.parent == tmp_path / "out"

def test_spaces_around_the_folder_are_ignored(tmp_path):
    [path] = export_tables([table()], "json", f"  {tmp_path}  ")
    assert path.parent == tmp_path

@pytest.mark.parametrize("args, message", [
    (([], "csv", "x"), "no tables"),
    (([table()], "docx", "x"), "Unknown format"),
    (([table()], "csv", "   "), "Choose a folder"),
    (([table()], "xlsx", ""), "Choose a folder"),
])
def test_bad_requests_give_a_friendly_error(args, message):
    with pytest.raises(ExportError, match=message):
        export_tables(*args)

def test_a_folder_that_is_really_a_file_is_a_friendly_error(tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("hi")
    for fmt in FORMATS:
        with pytest.raises(ExportError):
            export_tables([table()], fmt, str(blocker))

def test_describe():
    assert describe([Path("/a/b/Prices.csv")]) == f"Saved Prices.csv to {Path('/a/b')}."
    assert describe([Path("/a/b/One.csv"), Path("/a/b/Two.csv")]) == f"Saved 2 files to {Path('/a/b')}."