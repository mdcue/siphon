"""Tests for siphon_app/core/cleaner.py. Run them with:  pytest"""
from pathlib import Path

import pytest

from siphon_app.core.cleaner import clean_table, is_missing, parse_number
from siphon_app.core.models import Table
from siphon_app.core.parser import parse_tables

FIXTURES = Path(__file__).parent / "fixtures"

def make(headers, *columns):
    """Build a Table from columns: make(["A"], ["1", "2"]) is one column with two rows."""
    return Table("t", headers, [list(r) for r in zip(*columns)])

def value(text, decimal="."):
    parsed = parse_number(text, decimal)
    return None if parsed is None else parsed.value

#values that broke the old scraper

def test_the_values_that_used_to_become_blank():
    assert value("$1,234.50") == 1234.5
    assert value("$2.5B") == 2_500_000_000
    assert value("$2.5 B") == 2_500_000_000
    assert value("1,200%") == 1200

def test_the_prices_page_end_to_end():
    table = parse_tables((FIXTURES / "prices.html").read_bytes())[0]
    cleaned, report = clean_table(table)
    assert cleaned.headers == ["Name", "Price", "Cap", "Change (%)"]
    assert cleaned.rows[0] == ["Alpha", 1234.5, 1_500_000_000, 12]
    assert cleaned.rows[1] == ["Beta", 99, 2_500_000_000, -3.4]
    assert cleaned.rows[2] == ["Gamma", 5.25, 800_000_000, 1200]
    assert cleaned.rows[4] == ["Delta", 7, 3000, 0]
    #the merged cell row
    assert cleaned.rows[3] == ["Merged cell row", "Merged cell row", 1, 5]
    assert report.cells_kept_as_text == 1
    assert "kept as text" in report.summary()
    assert any("kept as text" in w for w in cleaned.warnings)

#single values

@pytest.mark.parametrize("text, expected", [
    ("42", 42), ("0", 0), ("3.14", 3.14), (".5", 0.5), ("1,234", 1234), ("1,234,567", 1234567),
    ("+7", 7), ("-7", -7), ("\u22127", -7), ("$-7", -7), ("-$7", -7), ("(1,234)", -1234), ("($3.4)", -3.4),
    ("\u20ac2.5M", 2_500_000), ("\u00a3800k", 800_000), ("\u00a51T", 10**12), ("\u20b95", 5),
    ("Rs 1,500", 1500), ("Rs.1,500", 1500), ("5 \u20ac", 5), ("1 234", 1234),
    ("12[1]", 12), ("5*", 5), ("7 [a]", 7), ("  9  ", 9),
])
def test_parse_number_accepts(text, expected):
    assert value(text) == expected

@pytest.mark.parametrize("text", [
    "", "abc", "12abc", "1.2.3", "1,23", "1,2345", "--5", "$", "%", "5 apples", "1-2",
    "12 34 5", "2020-01-05", "10:30", "5kg", "5 Bn", "(5", "5)",
])
def test_parse_number_rejects(text):
    assert parse_number(text) is None

def test_percent_is_a_plain_number_with_a_flag():
    assert parse_number("12.5%").value == 12.5
    assert parse_number("12.5%").is_percent
    assert not parse_number("12.5").is_percent

def test_results_are_exact_not_float_noise():
    assert value("$1.1") == 1.1
    assert value("0.1B") == 100_000_000 and isinstance(value("0.1B"), int)
    assert isinstance(value("5"), int) and isinstance(value("5.5"), float)

def test_comma_decimal_style():
    assert value("1.234,50", ",") == 1234.5
    assert value("2,5", ",") == 2.5
    assert value("\u20ac1.234", ",") == 1234
    assert value("1.234,50", ".") is None

def test_missing_markers():
    for text in ["", " ", "-", "\u2014", "\u2013", "N/A", "n/a", "NA", "None", "?"]:
        assert is_missing(text), text
    assert not is_missing("0")
    assert not is_missing("5")

#for whole columns
def test_a_mostly_numeric_column_is_converted_and_the_odd_cell_kept():
    table = make(["Price"], ["$1", "$2", "$3", "$4", "see note"])
    cleaned, report = clean_table(table)
    assert [r[0] for r in cleaned.rows] == [1, 2, 3, 4, "see note"]
    assert report.cells_converted == 4 and report.cells_kept_as_text == 1

def test_a_mostly_text_column_is_left_completely_alone():
    table = make(["Mixed"], ["$1", "$2", "apple", "pear", "plum"])
    cleaned, report = clean_table(table)
    assert [r[0] for r in cleaned.rows] == ["$1", "$2", "apple", "pear", "plum"]
    assert report.columns == []
    assert "nothing was changed" in report.summary()

def test_the_80_percent_line_is_exact():
    three_of_five = make(["N"], ["1", "2", "3", "a", "b"])
    four_of_five = make(["N"], ["1", "2", "3", "4", "b"])
    assert clean_table(three_of_five)[1].columns == []
    assert len(clean_table(four_of_five)[1].columns) == 1

def test_one_dollar_cell_no_longer_converts_the_whole_column():
    table = make(["Notes"], ["$5", "hello", "world", "again"])
    assert [r[0] for r in clean_table(table)[0].rows] == ["$5", "hello", "world", "again"]

def test_missing_markers_become_empty_only_inside_numeric_columns():
    numeric = make(["N"], ["5", "N/A", "\u2014", "7"])
    text = make(["T"], ["apple", "N/A", "\u2014", "pear"])
    assert [r[0] for r in clean_table(numeric)[0].rows] == [5, "", "", 7]
    assert [r[0] for r in clean_table(text)[0].rows] == ["apple", "N/A", "\u2014", "pear"]

def test_missing_cells_do_not_count_against_the_80_percent_rule():
    table = make(["N"], ["1", "2", "3", "4", "N/A", "N/A", "N/A", "N/A"])
    assert clean_table(table)[1].columns[0].converted == 4

def test_a_column_with_no_values_is_left_alone():
    cleaned, report = clean_table(make(["Empty"], ["", "", ""]))
    assert cleaned.rows == [[""], [""], [""]] and report.columns == []

def test_leading_zeros_mean_a_code_not_a_number():
    table = make(["Zip"], ["01234", "20500", "98101", "00501"])
    assert [r[0] for r in clean_table(table)[0].rows] == ["01234", "20500", "98101", "00501"]
    assert value("0.5") == 0.5 and value("0") == 0

def test_decimal_comma_column_is_detected():
    table = make(["Price"], ["1.234,50", "2,5", "10,75", "\u20ac3.000"])
    cleaned, report = clean_table(table)
    assert [r[0] for r in cleaned.rows] == [1234.5, 2.5, 10.75, 3000]
    assert report.columns[0].decimal == ","

def test_ambiguous_numbers_default_to_the_dot_style():
    table = make(["N"], ["1,234", "5,678", "9"])
    assert [r[0] for r in clean_table(table)[0].rows] == [1234, 5678, 9]

def test_percent_columns_get_a_unit_hint_once():
    table = make(["Change", "Share (%)", "Odd"], ["1%", "2%", "3%"], ["4%", "5%", "6%"], ["1%", "x", "y"])
    cleaned, _ = clean_table(table)
    assert cleaned.headers == ["Change (%)", "Share (%)", "Odd"]

def test_a_few_percent_signs_do_not_mark_the_whole_column_as_percent():
    table = make(["Score"], ["1%", "2", "3", "4", "5"])
    cleaned, report = clean_table(table)
    assert cleaned.headers == ["Score"] and not report.columns[0].is_percent

def test_keep_original_adds_the_untouched_column():
    table = make(["Price", "Name"], ["$1,000", "$2"], ["a", "b"])
    cleaned, _ = clean_table(table, keep_original = True)
    assert cleaned.headers == ["Price", "Price (original)", "Name"]
    assert cleaned.rows == [[1000, "$1,000", "a"], [2, "$2", "b"]]

def test_the_original_table_is_never_modified():
    table = make(["Price"], ["$1,000", "$2"])
    clean_table(table, keep_original=True)
    assert table.headers == ["Price"] and table.rows == [["$1,000"], ["$2"]]

def test_everything_else_about_the_table_is_carried_over():
    table = Table("Prices", ["A"], [["1"], ["2"]], source_url="http://x.test", warnings = ["w"], is_layout=True)
    cleaned, _ = clean_table(table)
    assert (cleaned.name, cleaned.source_url, cleaned.is_layout) == ("Prices", "http://x.test", True)
    assert cleaned.warnings == ["w"]

def test_a_table_with_no_rows_is_fine():
    cleaned, report = clean_table(Table("t", ["A", "B"], []))
    assert cleaned.rows == [] and cleaned.headers == ["A", "B"] and report.columns == []

def test_numbers_pass_the_models_row_check_with_the_original_row_count():
    table = make(["A", "B"], ["1", "2", "3"], ["x", "y", "z"])
    cleaned, _ = clean_table(table)
    assert cleaned.n_rows == 3 and cleaned.n_cols == 2
