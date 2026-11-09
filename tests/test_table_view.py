# [NEW FILE] every line is new
"""Tests for siphon_app/gui/table_view.py. The widget tests are skipped with no screen."""
import pytest

from siphon_app.core.models import Table
from siphon_app.gui.table_view import (
    ARROW_DOWN, ARROW_UP, CHECKED, MAX_PREVIEW_ROWS, UNCHECKED, TableView,
    display, filter_rows, is_numeric_column, rows_to_tsv, size_text, sort_rows,
)


# ---- helpers that need no window ---------------------------------------------------------

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
    assert prices == ["$9", "$10", "$100", ""]              # not "$10", "$100", "$9"


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
    assert is_numeric_column([["1"], ["$2"], ["3%"], ["4"], ["x"]], 0)            # 4 of 5 = 80%
    assert not is_numeric_column([["1"], ["a"], ["b"]], 0)
    assert not is_numeric_column([[""], [""]], 0)
    assert is_numeric_column([[1], [2.5], [""]], 0)


# ---- the widget --------------------------------------------------------------------------

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
    assert view.name_label.cget("text") == "Data"                  # the preview skips the hidden one


def test_showing_layout_tables_lists_them_unticked(make_view):
    data = table("Data", [["a", "1"]])
    menu = table("Menu", [["home", "x"]], is_layout=True)
    view = make_view([menu, data])
    view.hide_layout.set(False)
    view._refresh_list()
    assert listed(view) == ["Menu", "Data"]
    assert view.table_list.set("0", "use") == UNCHECKED            # layout: not ticked
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
    assert view.checked_tables() == [data]                         # Menu was never ticked


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
    view._on_search_key()                                          # the timer restarts, it doesn't double up
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
    view._sort_by(0)                                               # a different column starts ascending
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
    assert len(copied) == 1 + 1500                                 # header + every row
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


# ---- swapping versions and telling the window about changes (Step 9) ----------------------

def test_swap_tables_shows_new_versions_but_keeps_ticks_selection_and_search(make_view):
    a = table("A", [["x1", "$1"], ["x2", "$2"], ["y3", "$3"]])
    b = table("B", [["z", "$9"]])
    view = make_view([a, b])
    view.table_list.selection_set("1")
    view.update()
    view.toggle(0)                                                   # untick A
    view.table_list.selection_set("0")
    view.update()
    view.search_var.set("x")
    view._sort_by(0)
    cleaned = [table("A", [["x1", 1], ["x2", 2], ["y3", 3]]), table("B", [["z", 9]])]
    view.swap_tables(cleaned)
    assert shown(view) == [["x1", "1"], ["x2", "2"]]                 # same search, same sort, new values
    assert view.search_var.get() == "x" and view._sort_column == 0
    assert view.table_list.selection() == ("0",)
    assert view.checked_tables() == [cleaned[1]]                     # the tick on B survived; A stays unticked


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
    assert calls                                                     # new tables
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


# ---- Step 12: column tools and profile ---------------------------------------------------
# [NEW] everything from here down is new. `three()` is a small 3-column table to play with,
# and `headings(view)` reads the column names currently showing in the preview.

from siphon_app.gui import profile_window as pw
from siphon_app.gui.dialogs import ask_name


def three(name="T"):
    return Table(name, ["A", "B", "C"], [["a1", "$5", "c1"], ["a2", "$7", "c2"]])


def headings(view):
    return [view.preview.heading(c, "text") for c in view.preview["columns"]]


# -- hiding, renaming and resetting columns
def test_hiding_a_column_removes_it_from_preview_list_and_export(make_view):
    base = three()
    view = make_view([base])
    assert view.hide_column(1) is True
    assert headings(view) == ["A", "C"]
    assert shown(view) == [["a1", "c1"], ["a2", "c2"]]
    assert view.table_list.set("0", "size") == "2 × 2"
    assert view.size_label.cget("text") == "2 rows × 2 columns"
    exported = view.checked_tables()[0]
    assert exported.headers == ["A", "C"] and exported.rows == [["a1", "c1"], ["a2", "c2"]]
    assert base.headers == ["A", "B", "C"]


def test_hiding_more_columns_uses_the_columns_you_see(make_view):
    view = make_view([three()])
    view.hide_column(0)
    view.hide_column(1)
    assert headings(view) == ["B"]


def test_cannot_hide_the_last_column(make_view):
    messages = []
    view = make_view([three()], notify=messages.append)
    view.hide_column(0)
    view.hide_column(0)
    assert view.hide_column(0) is False
    assert headings(view) == ["C"]
    assert "at least one column" in messages[-1]


def test_hide_with_a_bad_position_or_no_table_does_nothing(make_view):
    view = make_view([three()])
    assert view.hide_column(7) is False and view.hide_column(-1) is False
    assert make_view().hide_column(0) is False
    assert headings(view) == ["A", "B", "C"]


def test_renaming_a_column(make_view):
    view = make_view([three()])
    assert view.rename_column(1, "  Price   (USD) ") is True
    assert headings(view) == ["A", "Price (USD)", "C"]
    assert view.checked_tables()[0].headers == ["A", "Price (USD)", "C"]


def test_renaming_to_nothing_is_refused_with_a_message(make_view):
    messages = []
    view = make_view([three()], notify=messages.append)
    assert view.rename_column(0, "   ") is False
    assert headings(view) == ["A", "B", "C"]
    assert messages == ["A column needs a name."]
    assert view.rename_column(9, "x") is False and make_view().rename_column(0, "x") is False


def test_rename_then_hide_keeps_names_on_the_right_columns(make_view):
    view = make_view([three()])
    view.rename_column(2, "Cee")
    view.hide_column(0)
    assert headings(view) == ["B", "Cee"]
    view.rename_column(0, "Bee")
    assert view.checked_tables()[0].headers == ["Bee", "Cee"]


def test_reset_columns_brings_everything_back(make_view):
    view = make_view([three()])
    view.hide_column(0)
    view.rename_column(0, "X")
    view.reset_columns()
    assert headings(view) == ["A", "B", "C"]
    assert view.checked_tables()[0].headers == ["A", "B", "C"]
    make_view().reset_columns()


# -- column changes stay with their own table, and survive or reset at the right moments
def test_column_changes_belong_to_one_table(make_view):
    view = make_view([three("One"), three("Two")])
    view.hide_column(0)
    view.table_list.selection_set("1")
    view.update()
    assert headings(view) == ["A", "B", "C"]
    view.table_list.selection_set("0")
    view.update()
    assert headings(view) == ["B", "C"]


def test_a_new_set_of_tables_forgets_column_changes(make_view):
    view = make_view([three()])
    view.hide_column(0)
    view.set_tables([three()])
    assert headings(view) == ["A", "B", "C"]


def test_swapping_to_cleaned_tables_keeps_column_changes(make_view):
    view = make_view([three()])
    view.hide_column(0)
    cleaned = Table("T", ["A", "B", "C"], [["a1", 5, "c1"], ["a2", 7, "c2"]])
    view.swap_tables([cleaned])
    assert headings(view) == ["B", "C"]
    assert view.checked_tables()[0].rows == [[5, "c1"], [7, "c2"]]


def test_changing_columns_resets_the_sort(make_view):
    view = make_view([three()])
    view._sort_by(2)
    view.hide_column(0)
    assert view._sort_column is None
    assert all(not t.endswith((ARROW_UP, ARROW_DOWN)) for t in headings(view))


def test_search_still_works_after_hiding(make_view):
    view = make_view([three()])
    view.hide_column(0)
    view.search_var.set("c2")
    view._apply_search()
    assert shown(view) == [["$7", "c2"]]


def test_copy_follows_the_visible_columns(make_view):
    view = make_view([three()])
    view.hide_column(0)
    view.copy_table()
    assert view.clipboard_get() == "B\tC\n$5\tc1\n$7\tc2\n"


# -- the rename box and the right-click menu (the dialog itself is faked so no pop-up appears)
def test_rename_asks_for_a_name_and_uses_the_answer(make_view):
    view = make_view([three()])
    asked = []
    view.ask_name = lambda parent, current: asked.append(current) or "Fresh"
    view._ask_rename(1)
    assert asked == ["B"] and headings(view)[1] == "Fresh"


def test_cancelling_the_rename_changes_nothing_and_says_nothing(make_view):
    messages = []
    view = make_view([three()], notify=messages.append)
    view.ask_name = lambda parent, current: None
    view._ask_rename(1)
    assert headings(view) == ["A", "B", "C"] and messages == []


def test_the_column_menu_has_the_three_actions(make_view):
    view = make_view([three()])
    menu = view.build_column_menu(1)
    labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)
              if menu.type(i) == "command"]
    assert labels == ["Rename...", "Hide this column", "Reset columns"]
    assert menu.entrycget(2 + 1, "state") == "disabled"
    menu.invoke(1)
    assert headings(view) == ["A", "C"]
    assert view.build_column_menu(0).entrycget(3, "state") == "normal"
    view.build_column_menu(0).invoke(3)
    assert headings(view) == ["A", "B", "C"]


def test_right_click_on_a_heading_opens_the_menu_and_elsewhere_does_not(make_view, monkeypatch):
    view = make_view([three()])
    view.update()
    posted = []
    monkeypatch.setattr("tkinter.Menu.tk_popup", lambda self, x, y: posted.append((x, y)))

    class Event:
        x, y, x_root, y_root = 30, 5, 100, 200

    monkeypatch.setattr(view.preview, "identify_region", lambda x, y: "heading")
    monkeypatch.setattr(view.preview, "identify_column", lambda x: "#2")
    view._on_preview_right_click(Event)
    assert posted == [(100, 200)]
    monkeypatch.setattr(view.preview, "identify_region", lambda x, y: "cell")
    view._on_preview_right_click(Event)
    monkeypatch.setattr(view.preview, "identify_region", lambda x, y: "heading")
    monkeypatch.setattr(view.preview, "identify_column", lambda x: "#9")
    view._on_preview_right_click(Event)
    assert len(posted) == 1


def test_the_tip_is_shown_and_footer_stays_empty(make_view):
    view = make_view([three()])
    assert "right-click" in view.tip_label.cget("text")
    assert view.footer_label.cget("text") == ""


# -- the profile window
def test_profile_button_opens_a_window_for_the_visible_columns(make_view):
    view = make_view([three()])
    view.hide_column(0)
    view.show_profile()
    window = view.profile_window
    rows = [window.grid_view.item(i, "values") for i in window.grid_view.get_children()]
    assert [r[0] for r in rows] == ["B", "C"]
    assert "Profile: T" in window.title()
    view.show_profile()
    assert not window.winfo_exists() and view.profile_window.winfo_exists()
    view.profile_window.destroy()


def test_profile_with_no_table_does_nothing(make_view):
    view = make_view()
    view.show_profile()
    assert view.profile_window is None


def test_format_number():
    assert pw.format_number(None) == ""
    assert pw.format_number(1234.0) == "1,234"
    assert pw.format_number(1234.567) == "1,234.57"
    assert pw.format_number(-5) == "-5"


def test_profile_rows_text():
    t = Table("T", ["Team", "Pts"], [["Red", "10"], ["Red", "20"], ["", "30"]])
    rows = pw.profile_rows(t)
    assert rows[0] == ("Team", "text", "2", "1", "1", "", "", "", "Red (2)")
    assert rows[1] == ("Pts", "number", "3", "0", "3", "10", "30", "20", "10 (1)")
    assert pw.summary_text(t) == "3 rows, 2 columns (1 numeric). 1 empty cells in total."


# -- the rename dialog itself
def make_dialog(app, current="Old"):
    import ttkbootstrap as ttk
    from siphon_app.gui.dialogs import NameDialog
    top = ttk.Toplevel(app)
    top.withdraw()
    return top, NameDialog(top, current)


def test_the_dialog_starts_with_the_current_name(app):
    top, dialog = make_dialog(app)
    try:
        assert dialog.value.get() == "Old" and dialog.result is None
    finally:
        top.destroy()


def test_the_dialog_returns_the_typed_name_on_accept(app):
    top, dialog = make_dialog(app)
    try:
        dialog.value.set("Typed")
        dialog.ok_button.invoke()
        assert dialog.result == "Typed" and not dialog.winfo_exists()
    finally:
        top.destroy()


def test_the_dialog_returns_none_on_cancel(app):
    top, dialog = make_dialog(app)
    try:
        dialog.value.set("Typed")
        dialog.cancel_button.invoke()
        assert dialog.result is None and not dialog.winfo_exists()
    finally:
        top.destroy()


def test_ask_name_waits_and_returns_the_answer(app):
    import ttkbootstrap as ttk
    top = ttk.Toplevel(app)
    top.withdraw()

    def answer():
        dialog = [w for w in top.winfo_children() if w.winfo_class() == "Toplevel"][0]
        dialog.value.set("Typed")
        dialog.accept()

    top.after(50, answer)
    try:
        assert ask_name(top, "Old") == "Typed"
    finally:
        top.destroy()


def test_dialogs_belong_to_their_parent(app):
    top, dialog = make_dialog(app)
    try:
        assert dialog.master is top
    finally:
        top.destroy()


def test_the_profile_window_belongs_to_the_view(make_view):
    view = make_view([three()])
    view.show_profile()
    try:
        assert view.profile_window.master is view
    finally:
        view.profile_window.destroy()


def test_an_empty_column_has_no_most_common_text():
    t = Table("T", ["A"], [[""], ["-"]])
    assert pw.profile_rows(t) == [("A", "empty", "0", "2", "0", "", "", "", "")]
