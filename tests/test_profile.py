# Tests for siphon_app/core/profile.py: the per-column summary
import pytest

from siphon_app.core.models import Table
from siphon_app.core.profile import EMPTY, NUMBER, TEXT, profile_column, profile_table

# money text still counts as numbers; the blank is counted as empty

def test_number_column_has_min_max_mean():
    p = profile_column("Price", ["$10", "$20", "$30", ""])
    assert (p.kind, p.filled, p.empty, p.unique) == (NUMBER, 3, 1, 3)
    assert (p.minimum, p.maximum, p.mean) == (10, 30, 20)

# works after the cleaner too, when cells are real numbers

def test_numbers_already_cleaned_work_too():
    p = profile_column("n", [1, 2.5, 4])
    assert p.kind == NUMBER and p.minimum == 1 and p.maximum == 4 and p.mean == pytest.approx(7.5 / 3)

# text columns get counts and a most-common value, but no min/max/mean

def test_text_column_counts_unique_and_most_common():
    p = profile_column("Team", ["Red", "Blue", "Red", "Red", "Blue", ""])
    assert (p.kind, p.filled, p.empty, p.unique) == (TEXT, 5, 1, 2)
    assert (p.common, p.common_count) == ("Red", 3)
    assert p.minimum is None and p.maximum is None and p.mean is None

# when two values tie for most common, the one seen first wins

def test_ties_pick_the_first_seen_value():
    p = profile_column("x", ["b", "a", "a", "b"])
    assert p.common == "b" and p.common_count == 2

# '-', 'N/A', a long dash, '?' and spaces all mean 'no value'

def test_empty_markers_count_as_empty():
    p = profile_column("x", ["a", "-", "N/A", "n/a", "—", "  ", None and "z" or "?"])
    assert p.filled == 1 and p.empty == 6

# nothing filled at all means kind 'empty'

def test_all_empty_column():
    p = profile_column("x", ["", "-", " "])
    assert (p.kind, p.filled, p.empty, p.unique, p.common, p.common_count) == (EMPTY, 0, 3, 0, "", 0)

# a table with no rows doesn't crash the profile

def test_no_rows_at_all_is_an_empty_column():
    p = profile_column("x", [])
    assert p.kind == EMPTY and p.filled == 0 and p.empty == 0

# 0 is a real value, not a blank

def test_a_zero_is_filled_not_empty():
    p = profile_column("x", [0, 0.0, 5])
    assert p.filled == 3 and p.empty == 0 and p.kind == NUMBER

# the 80% line, same rule as the cleaner: exactly 80% is a number column, 60% is text

def test_eighty_percent_numeric_counts_as_numbers_and_just_under_does_not():
    assert profile_column("x", ["1", "2", "3", "4", "oops"]).kind == NUMBER
    assert profile_column("x", ["1", "2", "3", "oops", "nope"]).kind == TEXT

# the odd text cell in a number column is skipped for min/max/average but still counted

def test_numeric_stats_only_use_the_cells_that_parse():
    p = profile_column("x", ["1", "2", "3", "4", "oops"])
    assert (p.minimum, p.maximum, p.mean) == (1, 4, 2.5)
    assert p.filled == 5 and p.unique == 5

# 12%, (5) and -3 all read as numbers, negatives included

def test_percent_and_negative_numbers():
    p = profile_column("x", ["12%", "(5)", "-3"])
    assert (p.minimum, p.maximum) == (-5, 12)

# 'a', ' a' and 'a ' are one value

def test_values_are_compared_after_stripping_spaces():
    assert profile_column("x", ["a", " a", "a "]).unique == 1

# True/False must not sneak in as 1/0

def test_booleans_are_not_numbers():
    assert profile_column("x", [True, False]).kind == TEXT

# one profile per column, in column order

def test_profile_table_gives_one_profile_per_column_in_order():
    table = Table("T", ["A", "B"], [["x", 1], ["y", 2], ["x", ""]])
    a, b = profile_table(table)
    assert (a.name, a.kind, a.unique, a.common) == ("A", TEXT, 2, "x")
    assert (b.name, b.kind, b.filled, b.empty, b.maximum) == ("B", NUMBER, 2, 1, 2)

# no rows: every column is 'empty'

def test_profile_table_with_no_rows():
    profiles = profile_table(Table("T", ["A", "B"], []))
    assert [p.kind for p in profiles] == [EMPTY, EMPTY]
