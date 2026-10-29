"""Tests for siphon_app/gui/table_view.py. The widget tests are skipped with no screen."""
import pytest

from siphon_app.core.models import Table
from siphon_app.gui.table_view import (
    ARROW_DOWN, ARROW_UP, CHECKED, MAX_PREVIEW_ROWS, UNCHECKED, TableView,
    display, filter_rows, is_numeric_column, rows_to_tsv, size_text, sort_rows,
)

#helpers
ROWS = [["Alpha", "$10", "x"], ["beta", "$9", "y"], ["Gamma", "$100", "x z"], ["Delta", "", "x"]]

def test_filter_rows_matches_any_column_ignoring_capitals():
    assert filter_rows(ROWS, "ALPHA") == [ROWS[0]]
    assert filter_rows(ROWS, "$9") == [ROWS[1]]
    assert filter_rows(ROWS, "x") == [ROWS[0], ROWS[2], ROWS[3]]

def test_filter_rows_needs_every_word_but_in_any_order():
    assert filter_rows(ROWS, "gamma x") == [ROWS[2]]
    assert filter_rows(ROWS, "x gamma") == [ROWS[2]]
    assert filter_rows(ROWS, "gamma nothing") == []

def test_filter_rows_with_an_empty_query_keeps_everything():
    assert filter_rows(ROWS, "") == ROWS
    assert filter_rows(ROWS, "   ") == ROWS

def test_filter_rows_finds_numbers():
    assert filter_rows([["a", 1234.5], ["b", 7]], "1234") == [["a", 1234.5]]

def test_sort_text_ignores_capitals():
    names = [row[0] for row in sort_rows(ROWS, 0)]
    assert names == ["Alpha", "beta", "Delta", "Gamma"]

def test_sort_understands_money_so_100_comes_after_9():
    prices = [row[1] for row in sort_rows(ROWS, 1)]
    assert prices == ["$9", "$10", "$100", ""] # not "$10", "$100", "$9"

def test_sort_descending_still_puts_blanks_last():
    prices = [row[1] for row in sort_rows(ROWS, 1, descending=True)]
    assert prices == ["$100", "$10", "$9", ""]

def test_sort_numbers_stored_as_numbers_and_mixed_columns():
    rows = [["b"], [10], ["a"], [2.5], [""]]
    assert [r[0] for r in sort_rows(rows, 0)] == [2.5, 10, "a", "b", ""]

def test_sort_keeps_the_original_order_of_equal_rows():
    rows = [["x", "1"], ["y", "1"], ["z", "1"]]
    assert [r[0] for r in sort_rows(rows, 1)] == ["x", "y", "z"]
    assert [r[0] for r in sort_rows(rows, 1, descending=True)] == ["x", "y", "z"]

def test_sort_does_not_change_the_list_it_was_given():
    original = [row[:] for row in ROWS]
    sort_rows(ROWS, 1)
    assert ROWS == original

def test_rows_to_tsv_pastes_into_excel_cleanly():
    text = rows_to_tsv(["A", "B"], [["1", "two\twords"], ["line\nbreak", 3.5]])
    assert text == "A\tB\n1\ttwo words\nline break\t3.5\n"

def test_size_text_and_display():
    assert size_text(Table("t", ["A", "B"], [["1", "2"]] * 1234)) == "1,234 \u00d7 2"
    assert display(None) == "" and display(5) == "5" and display("x") == "x"

def test_is_numeric_column():
    assert is_numeric_column([["1"], ["$2"], ["3%"], ["4"], ["x"]], 0) # 4 of 5 = 80%
    assert not is_numeric_column([["1"], ["a"], ["b"]], 0)
    assert not is_numeric_column([[""], [""]], 0)
    assert is_numeric_column([[1], [2.5], [""]], 0)

#the widget
@pytest.fixture
def make_view(app):
    """Build a TableView in its own little window, and tidy it away after the test."""
    import ttkbootstrap as ttk
    windows = []

    def make(tables=(), notify=None):
        top = ttk.Toplevel(app)
        top.withdraw()
        windows.append(top)
        view = TableView(top, notify=notify)
        view.pack()
        view.set_tables(list(tables))
        return view

    yield make
    for top in windows:
        top.destroy()

def table(name, rows, headers=("Name", "Price"), is_layout=False):
    return Table(name, list(headers), [list(r) for r in rows], is_layout=is_layout)

def listed(view):
    return [view.table_list.set(i, "name") for i in view.table_list.get_children()]

def shown(view):
    """The preview rows as plain lists of text (Tk turns '5' into 5, so we compare as text)."""
    return [[str(v) for v in view.preview.item(i, "values")] for i in view.preview.get_children()]

def test_starts_with_a_placeholder_and_no_tables(make_view):
    view = make_view()
    assert view.placeholder.cget("text") == "Tables will show up here."
    assert view.checked_tables() == [] and view.table_list.get_children() == ()

def test_lists_tables_with_sizes_and_previews_the_first(make_view):
    a = table("Prices", [["Alpha", "$1"], ["Beta", "$2"]])
    b = table("Other", [["x", "y"]], headers=("A", "B"))
    view = make_view([a, b])
    assert listed(view) == ["Prices", "Other"]
    assert view.table_list.set("0", "size") == "2 \u00d7 2"
    assert view.list_title.cget("text") == "Tables found (2)"
    assert view.name_label.cget("text") == "Prices"
    assert view.size_label.cget("text") == "2 rows \u00d7 2 columns"
    assert shown(view) == [["Alpha", "$1"], ["Beta", "$2"]]
    assert [view.preview.heading(c, "text") for c in view.preview["columns"]] == ["Name", "Price"]

def test_layout_tables_are_hidden_and_unticked_by_default(make_view):
    data = table("Data", [["a", "1"], ["b", "2"]])
    menu = table("Menu", [["home", "x"]], is_layout=True)
    view = make_view([menu, data])
    assert listed(view) == ["Data"]
    assert view.hint_label.cget("text") == "1 layout table hidden."
    assert view.checked_tables() == [data]
    assert view.name_label.cget("text") == "Data" # the preview skips the hidden one

def test_showing_layout_tables_lists_them_unticked(make_view):
    data = table("Data", [["a", "1"]])
    menu = table("Menu", [["home", "x"]], is_layout=True)
    view = make_view([menu, data])
    view.hide_layout.set(False)
    view._refresh_list()
    assert listed(view) == ["Menu", "Data"]
    assert view.table_list.set("0", "use") == UNCHECKED # layout: not ticked
    assert view.table_list.set("1", "use") == CHECKED
    assert view.checked_tables() == [data]
    assert view.hint_label.cget("text") == ""

def test_when_every_table_is_layout_it_explains_how_to_see_them(make_view):
    view = make_view([table("Menu", [["a", "b"]], is_layout=True), table("Nav", [["c", "d"]], is_layout=True)])
    assert view.table_list.get_children() == ()
    assert "All 2 tables look like page layout" in view.hint_label.cget("text")
    assert view.name_label.cget("text") == "" and shown(view) == []
    view.hide_layout.set(False)
    view._refresh_list()
    assert listed(view) == ["Menu", "Nav"]
    assert shown(view) == [["a", "b"]]

def test_ticking_boxes_and_select_all_none(make_view):
    a, b, c = (table(n, [["1", "2"]]) for n in "ABC")
    view = make_view([a, b, c])
    assert view.checked_tables() == [a, b, c]
    view.toggle(1)
    assert view.checked_tables() == [a, c]
    assert view.table_list.set("1", "use") == UNCHECKED
    view.select_none()
    assert view.checked_tables() == []
    view.select_all()
    assert view.checked_tables() == [a, b, c]
    view.toggle(2)
    view.toggle(2)
    assert view.checked_tables() == [a, b, c]

def test_select_all_does_not_tick_hidden_layout_tables(make_view):
    data = table("Data", [["a", "1"]])
    menu = table("Menu", [["home", "x"]], is_layout=True)
    view = make_view([menu, data])
    view.select_none()
    view.select_all()
    assert view.checked_tables() == [data]
    view.hide_layout.set(False)
    view._refresh_list()
    assert view.checked_tables() == [data] # Menu was never ticked

def test_choosing_another_table_changes_the_preview(make_view):
    a = table("First", [["1", "2"]])
    b = table("Second", [["3", "4"], ["5", "6"]], headers=("X", "Y"))
    view = make_view([a, b])
    view.table_list.selection_set("1")
    view.update()
    assert view.name_label.cget("text") == "Second"
    assert shown(view) == [["3", "4"], ["5", "6"]]
    assert [view.preview.heading(c, "text") for c in view.preview["columns"]] == ["X", "Y"]

def test_search_filters_the_preview_and_clearing_restores_it(make_view):
    rows = [["Alpha", "1"], ["Beta", "2"], ["Gamma", "3"], ["Alphabet", "4"]]
    view = make_view([table("T", rows)])
    view.search_var.set("alpha")
    view._apply_search()
    assert shown(view) == [["Alpha", "1"], ["Alphabet", "4"]]
    assert view.footer_label.cget("text") == "2 of 4 rows match."
    view.search_var.set("")
    view._apply_search()
    assert len(shown(view)) == 4 and view.footer_label.cget("text") == ""

def test_typing_in_the_search_box_filters_after_a_short_pause(make_view):
    view = make_view([table("T", [["Alpha", "1"], ["Beta", "2"]])])
    view.search_var.set("beta")
    view._on_search_key()
    view._on_search_key() # the timer restarts, it doesn't double up
    import time
    end = time.time() + 2
    while len(shown(view)) != 1 and time.time() < end:
        view.update()
        time.sleep(0.01)
    assert shown(view) == [["Beta", "2"]]

def test_clicking_a_heading_sorts_and_clicking_again_reverses(make_view):
    rows = [["a", "$10"], ["b", "$9"], ["c", "$100"]]
    view = make_view([table("T", rows)])
    view._sort_by(1)
    assert [r[1] for r in shown(view)] == ["$9", "$10", "$100"]
    assert view.preview.heading("1", "text").startswith("Price") and ARROW_UP in view.preview.heading("1", "text")
    view._sort_by(1)
    assert [r[1] for r in shown(view)] == ["$100", "$10", "$9"]
    assert ARROW_DOWN in view.preview.heading("1", "text")
    view._sort_by(0) # a different column starts ascending
    assert [r[0] for r in shown(view)] == ["a", "b", "c"]
    assert ARROW_UP not in view.preview.heading("1", "text")

def test_search_and_sort_work_together(make_view):
    rows = [["ax", "3"], ["bx", "1"], ["cy", "2"], ["dx", "2"]]
    view = make_view([table("T", rows)])
    view.search_var.set("x")
    view._sort_by(1)
    assert shown(view) == [["bx", "1"], ["dx", "2"], ["ax", "3"]]

def test_switching_table_resets_search_and_sort(make_view):
    view = make_view([table("A", [["a", "1"], ["b", "2"]]), table("B", [["c", "3"], ["d", "4"]])])
    view.search_var.set("a")
    view._sort_by(0)
    view.table_list.selection_set("1")
    view.update()
    assert view.search_var.get() == "" and view._sort_column is None
    assert len(shown(view)) == 2

def test_big_tables_show_a_capped_preview_but_copy_everything(make_view, app):
    rows = [[f"row {i}", str(i)] for i in range(MAX_PREVIEW_ROWS + 500)]
    notes = []
    view = make_view([table("Big", rows)], notify=notes.append)
    assert len(view.preview.get_children()) == MAX_PREVIEW_ROWS
    assert "first 1,000 of 1,500 rows" in view.footer_label.cget("text")
    view.copy_table()
    copied = view.clipboard_get().splitlines()
    assert len(copied) == 1 + 1500  # header + every row
    assert copied[0] == "Name\tPrice" and copied[-1] == "row 1499\t1499"
    assert notes == ["Copied 1,500 rows to the clipboard."]

def test_copy_follows_the_search_and_sort(make_view):
    rows = [["ax", "3"], ["bx", "1"], ["cy", "2"]]
    notes = []
    view = make_view([table("T", rows)], notify=notes.append)
    view.search_var.set("x")
    view._sort_by(1)
    view.copy_table()
    assert view.clipboard_get() == "Name\tPrice\nbx\t1\nax\t3\n"
    assert notes == ["Copied 2 rows to the clipboard."]

def test_copy_with_nothing_to_copy_does_nothing(make_view):
    notes = []
    view = make_view(notify=notes.append)
    view.copy_table()
    assert notes == []

def test_numbers_are_right_aligned_and_text_left_aligned(make_view):
    view = make_view([table("T", [["a", "$1"], ["b", "$22"], ["c", "$3"]])])
    assert str(view.preview.column("0", "anchor")) == "w"
    assert str(view.preview.column("1", "anchor")) == "e"

def test_awkward_cell_text_is_shown_as_is(make_view):
    odd = ["{braces}", "back\\slash", "with space", "100", "", "0012"]
    view = make_view([table("T", [odd[i:i + 2] for i in range(0, 6, 2)])])
    assert shown(view) == [["{braces}", "back\\slash"], ["with space", "100"], ["", "0012"]]

def test_loading_new_tables_replaces_the_old_ones(make_view):
    view = make_view([table("Old", [["a", "1"]])])
    view.set_tables([table("New", [["b", "2"]])])
    assert listed(view) == ["New"] and shown(view) == [["b", "2"]]
    view.set_tables([], "No tables found on that page.")
    assert view.placeholder.cget("text") == "No tables found on that page."
    assert view.checked_tables() == [] and view.table_list.get_children() == ()

def test_a_table_with_no_rows_still_previews_its_headers(make_view):
    view = make_view([table("Empty", [], headers=("A", "B"))])
    assert shown(view) == [] and view.size_label.cget("text") == "0 rows \u00d7 2 columns"
    assert [view.preview.heading(c, "text") for c in view.preview["columns"]] == ["A", "B"]

def test_swap_tables_shows_new_versions_but_keeps_ticks_selection_and_search(make_view):
    a = table("A", [["x1", "$1"], ["x2", "$2"], ["y3", "$3"]])
    b = table("B", [["z", "$9"]])
    view = make_view([a, b])
    view.table_list.selection_set("1")
    view.update()
    view.toggle(0)  # untick A
    view.table_list.selection_set("0")
    view.update()
    view.search_var.set("x")
    view._sort_by(0)
    cleaned = [table("A", [["x1", 1], ["x2", 2], ["y3", 3]]), table("B", [["z", 9]])]
    view.swap_tables(cleaned)
    assert shown(view) == [["x1", "1"], ["x2", "2"]] # same search, same sort, new values
    assert view.search_var.get() == "x" and view._sort_column == 0
    assert view.table_list.selection() == ("0",)
    assert view.checked_tables() == [cleaned[1]] # the tick on B survived; A stays unticked

def test_copy_after_a_swap_copies_the_new_version(make_view):
    view = make_view([table("A", [["x", "$1,000"]])])
    view.swap_tables([table("A", [["x", 1000]])])
    view.copy_table()
    assert view.clipboard_get() == "Name\tPrice\nx\t1000\n"

def test_swap_tables_needs_the_same_number_of_tables(make_view):
    view = make_view([table("A", [["x", "1"]])])
    with pytest.raises(ValueError):
        view.swap_tables([])

def test_swapping_with_nothing_selected_is_fine(make_view):
    view = make_view()
    view.swap_tables([])
    assert view.checked_tables() == []

def test_on_change_fires_when_ticks_or_tables_change(make_view):
    a, b = table("A", [["x", "1"]]), table("B", [["y", "2"]], is_layout=True)
    view = make_view()
    calls = []
    view.on_change = lambda: calls.append(1)
    view.set_tables([a, b])
    assert calls # new tables
    calls.clear()
    view.toggle(0)
    assert calls
    calls.clear()
    view.select_none()
    assert calls
    calls.clear()
    view.select_all()
    assert calls
    calls.clear()
    view.hide_layout.set(False)
    view._refresh_list()
    assert calls
    calls.clear()
    view.set_tables([])
    assert calls