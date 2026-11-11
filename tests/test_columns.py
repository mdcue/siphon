# Tests for siphon_app/core/columns.py: hiding and renaming columns on a copy.
import pytest

from siphon_app.core.columns import ColumnError, clean_name, reshape, visible_columns
from siphon_app.core.models import Table

def make():
    return Table("T", ["A", "B", "C"], [[1, "x", "p"], [2, "y", "q"]],
                source_url="http://e.x", warnings=["w"], is_layout=True)

# stray spaces and line breaks in a typed name get tidied
def test_clean_name_trims_and_collapses_spaces():
    assert clean_name("  Unit   price \n") == "Unit price"

# a blank name is not a name
@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_clean_name_refuses_blank(text):
    with pytest.raises(ColumnError):
        clean_name(text)

# None (a cancelled box) is refused the same way
def test_clean_name_refuses_none():
    with pytest.raises(ColumnError):
        clean_name(None)

# hidden columns drop out, the rest keep their order
def test_visible_columns_skips_hidden_in_order():
    assert visible_columns(4, {1, 3}) == [0, 2]
    assert visible_columns(3, set()) == [0, 1, 2]

# no hides, no renames: we get the very same table back, no copy
def test_reshape_with_nothing_to_do_returns_the_same_table():
    table = make()
    assert reshape(table) is table
    assert reshape(table, set(), {}) is table

# hiding removes the column from the headers AND from every row
def test_reshape_hides_columns_in_headers_and_rows():
    out = reshape(make(), hidden={1})
    assert out.headers == ["A", "C"]
    assert out.rows == [[1, "p"], [2, "q"]]

# renames point at ORIGINAL positions, so they survive other columns being hidden
def test_reshape_renames_by_original_position():
    out = reshape(make(), hidden={0}, names={2: "Cee", 1: "Bee"})
    assert out.headers == ["Bee", "Cee"]
    assert out.rows == [["x", "p"], ["y", "q"]]

# the copy keeps name, url, warnings and layout flag, and editing it never changes the original
def test_reshape_keeps_the_other_fields_and_does_not_touch_the_original():
    table = make()
    out = reshape(table, hidden={1}, names={0: "Z"})
    assert (out.name, out.source_url, out.warnings, out.is_layout) == ("T", "http://e.x", ["w"], True)
    assert out.warnings is not table.warnings
    assert table.headers == ["A", "B", "C"] and table.rows[0] == [1, "x", "p"]
    out.rows[0][0] = 99
    assert table.rows[0][0] == 1

# a table with zero columns makes no sense, so that's refused
def test_reshape_refuses_hiding_everything():
    with pytest.raises(ColumnError, match="at least one column"):
        reshape(make(), hidden={0, 1, 2})

# positions that don't exist (too big, negative) are refused
@pytest.mark.parametrize("hidden,names", [({3}, {}), ({-1}, {}), (set(), {5: "x"})])
def test_reshape_refuses_missing_columns(hidden, names):
    with pytest.raises(ColumnError):
        reshape(make(), hidden=hidden, names=names)

# renaming only changes headers, no rows get lost
def test_rename_alone_keeps_every_row():
    out = reshape(make(), names={0: "Z"})
    assert out.headers == ["Z", "B", "C"] and out.n_rows == 2