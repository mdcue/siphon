"""Tests for siphon_app/gui/grid.py: the canvas grid that draws only what you can see."""
import pytest

from siphon_app.gui.grid import (
    ARROW_DOWN, ARROW_UP, HANDLE, MIN_WIDTH, PAD, GridView, blend, shorten,
)

# helpers that need no window
# a fake 'measure': every character is 10 pixels wide
def ten(text):
    return 10 * len(text)

# text that fits is left alone
def test_shorten_keeps_text_that_fits():
    assert shorten("hello", 50, ten) == "hello"
    assert shorten("hello", 100, ten) == "hello"
    assert shorten("", 5, ten) == ""

# text that doesn't fit is cut so that text + the ellipsis fits exactly
def test_shorten_cuts_to_the_longest_piece_that_fits_with_an_ellipsis():
    assert shorten("abcdefghij", 50, ten) == "abcd…"             # 4 letters + the ellipsis = 50 px
    assert shorten("abcdefghij", 55, ten) == "abcd…"

# when even one letter doesn't fit, you still get the ellipsis (never an empty or overlong cell)
def test_shorten_with_almost_no_room_gives_just_the_ellipsis():
    assert shorten("abcdefghij", 5, ten) == "…"
    assert shorten("abcdefghij", 10, ten) == "…"

# blending moves a share of the way from one colour to the other
def test_blend_mixes_two_colours():
    assert blend("#000000", "#ffffff", 0) == "#000000"
    assert blend("#000000", "#ffffff", 1) == "#ffffff"
    assert blend("#000000", "#ffffff", 0.5) == "#808080"
    assert blend("#ff0000", "#0000ff", 0.25) == "#bf0040"

# the grid itself
# a grid in a throwaway window, with every callback recorded
@pytest.fixture
def make_grid(app):
    import ttkbootstrap as ttk
    tops, calls = [], {"sort": [], "menu": [], "resize": []}

    def make(headers=("Name", "Price"), rows=(("Alpha", "$1"), ("Beta", "$2"), ("Gamma", "$3")),
            widths=None, aligns=None):
        top = ttk.Toplevel(app)
        top.withdraw()
        tops.append(top)
        grid = GridView(top, on_sort=calls["sort"].append,
                        on_menu=lambda c, x, y: calls["menu"].append((c, x, y)),
                        on_resize=lambda c, w: calls["resize"].append((c, w)))
        grid.pack(fill="both", expand=True)
        grid.set_data(list(headers), [list(r) for r in rows], widths or [100] * len(headers),
                      aligns or ["w"] * len(headers))
        grid.update_idletasks()
        grid._redraw()                                  # draw now instead of waiting for the idle moment
        return grid, calls

    yield make
    for top in tops:
        top.destroy()

class Click:
    """A pretend mouse event."""
    def __init__(self, x=0, y=0, delta=0, x_root=0, y_root=0):
        self.x, self.y, self.delta, self.x_root, self.y_root = x, y, delta, x_root, y_root

# the rows and cells you gave are the ones drawn
def test_it_draws_the_cells_it_was_given(make_grid):
    grid, _ = make_grid()
    assert grid.rows == [["Alpha", "$1"], ["Beta", "$2"], ["Gamma", "$3"]]
    assert [(r, c, t) for r, c, t in grid.drawn] == [
        (0, 0, "Alpha"), (0, 1, "$1"), (1, 0, "Beta"), (1, 1, "$2"), (2, 0, "Gamma"), (2, 1, "$3")]
    assert grid.heading_texts() == ["Name", "Price"]

# the headings show the sort arrow on the sorted column only
def test_headings_show_the_sort_arrow(make_grid):
    grid, _ = make_grid()
    grid.set_data(["A", "B"], [["x", "y"]], [100, 100], ["w", "w"], sort_column=1, sort_descending=False)
    assert grid.heading_texts() == ["A", "B" + ARROW_UP]
    grid.set_data(["A", "B"], [["x", "y"]], [100, 100], ["w", "w"], sort_column=0, sort_descending=True)
    assert grid.heading_texts() == ["A" + ARROW_DOWN, "B"]

# a cell too long for its column is cut with an ellipsis (and the full text is kept)
def test_long_cells_are_cut_to_the_column_width(make_grid):
    grid, _ = make_grid(headers=("A",), rows=[("x" * 200,)], widths=[80])
    text = grid.drawn[0][2]
    assert text.endswith("…") and len(text) < 200
    assert grid.font.measure(text) <= 80 - 2 * PAD
    assert grid.rows[0][0] == "x" * 200

# a cell that is empty draws nothing but is still counted as drawn
def test_empty_cells_draw_no_text(make_grid):
    grid, _ = make_grid(headers=("A", "B"), rows=[("", "b")])
    assert (0, 0, "") in grid.drawn
    texts = [grid.body.itemcget(i, "text") for i in grid.body.find_all() if grid.body.type(i) == "text"]
    assert texts == ["b"]

# right-aligned columns put their text against the right edge
def test_right_aligned_columns_anchor_east(make_grid):
    grid, _ = make_grid(headers=("A", "B"), rows=[("l", "r")], widths=[100, 100], aligns=["w", "e"])
    anchors = {grid.body.itemcget(i, "text"): grid.body.itemcget(i, "anchor")
            for i in grid.body.find_all() if grid.body.type(i) == "text"}
    assert anchors == {"l": "w", "r": "e"}

# only the cells around the screen are drawn, however big the table is
def test_only_the_cells_around_the_screen_are_drawn(make_grid):
    rows = [[f"r{r}c{c}" for c in range(50)] for r in range(1000)]
    grid, _ = make_grid(headers=[f"H{c}" for c in range(50)], rows=rows, widths=[100] * 50, aligns=["w"] * 50)
    assert 0 < len(grid.drawn) < 1500                              # of 50,000 cells
    assert {c for _, c, _ in grid.drawn} == set(range(16))        # the 800 px view + one more screen: 1,600 px
    assert max(r for r, _, _ in grid.drawn) == int(800 // grid.row_height)

# scrolling far away and redrawing draws the cells that are now around the view, with the right text
def test_a_redraw_after_scrolling_draws_the_cells_around_the_new_view(make_grid):
    rows = [[f"r{r}c{c}" for c in range(50)] for r in range(1000)]
    grid, _ = make_grid(headers=[f"H{c}" for c in range(50)], rows=rows, widths=[100] * 50, aligns=["w"] * 50)
    grid.body.yview_scroll(100, "units")
    grid.body.xview_scroll(2400, "units")                         # 1 unit = 1 px: 2,400 px is column 24
    grid._redraw()
    cells = {(r, c) for r, c, _ in grid.drawn}
    assert (100, 24) in cells and (0, 0) not in cells
    assert all(text == f"r{r}c{c}" for r, c, text in grid.drawn)
    assert min(c for _, c in cells) >= 24 - 8 - 1 and max(r for r, _ in cells) < 100 + 40

# scrolling a little reuses what is drawn (Tk slides the items), so nothing is redrawn
def test_a_small_scroll_does_not_redraw(make_grid):
    rows = [[f"r{r}c{c}" for c in range(50)] for r in range(1000)]
    grid, _ = make_grid(headers=[f"H{c}" for c in range(50)], rows=rows, widths=[100] * 50, aligns=["w"] * 50)
    before = grid.drawn
    grid.body.yview_scroll(3, "units")
    grid.body.xview_scroll(3, "units")
    grid.update_idletasks()
    grid.update_idletasks()
    assert grid.drawn is before

def test_scrolling_down_does_not_touch_the_sideways_scroll_bar(make_grid):
    rows = [[f"r{r}c{c}" for c in range(50)] for r in range(1000)]
    grid, _ = make_grid(headers=[f"H{c}" for c in range(50)], rows=rows, widths=[100] * 50, aligns=["w"] * 50)
    grid.update_idletasks()
    sets = []
    real = grid.hbar.set
    grid.hbar.set = lambda *a: (sets.append(a), real(*a))
    for _ in range(5):
        grid.body.yview_scroll(1, "units")
        grid.update_idletasks()
    assert sets == []

def test_scrolling_sideways_still_moves_the_bar_and_the_headings(make_grid):
    rows = [[f"r{r}c{c}" for c in range(50)] for r in range(100)]
    grid, _ = make_grid(headers=[f"H{c}" for c in range(50)], rows=rows, widths=[100] * 50, aligns=["w"] * 50)
    grid._on_xscrolled(0.25, 0.5)
    assert grid.hbar.get() == pytest.approx((0.25, 0.5))
    assert grid.header.xview()[0] == pytest.approx(0.25, abs=0.01)   # snaps to whole steps

# scrolling past the drawn area redraws, in each of the four directions
@pytest.mark.parametrize("direction", ["down", "right", "up", "left"])
def test_scrolling_past_the_drawn_area_redraws(make_grid, direction):
    rows = [[f"r{r}c{c}" for c in range(50)] for r in range(1000)]
    grid, _ = make_grid(headers=[f"H{c}" for c in range(50)], rows=rows, widths=[100] * 50, aligns=["w"] * 50)
    if direction in ("up", "left"):                               # first go somewhere, so there is room to go back
        grid.body.yview_scroll(300, "units")
        grid.body.xview_scroll(4800, "units")
        grid._redraw()
    before = grid.drawn
    far = {"down": ("y", 100), "right": ("x", 2400), "up": ("y", -100), "left": ("x", -2400)}[direction]
    getattr(grid.body, f"{far[0]}view_scroll")(far[1], "units")
    grid.update_idletasks()
    grid.update_idletasks()
    assert grid.drawn is not before

# the last stretch of the data is drawn to the edge, and scrolling to the very end works
def test_scrolling_to_the_end_draws_the_last_rows_and_columns(make_grid):
    rows = [[f"r{r}c{c}" for c in range(50)] for r in range(1000)]
    grid, _ = make_grid(headers=[f"H{c}" for c in range(50)], rows=rows, widths=[100] * 50, aligns=["w"] * 50)
    grid.body.yview_moveto(1)
    grid.body.xview_moveto(1)
    grid.update_idletasks()
    grid.update_idletasks()
    cells = {(r, c) for r, c, _ in grid.drawn}
    assert (999, 49) in cells

# clicking a row highlights it, clicking below the data clears it
def test_clicking_a_row_selects_it(make_grid):
    grid, _ = make_grid()
    grid._on_body_click(Click(y=grid.row_height + 3))
    assert grid.selected == 1
    grid._on_body_click(Click(y=grid.row_height * 10))
    assert grid.selected is None

# the highlight is dropped when new data has fewer rows
def test_the_selection_is_dropped_when_the_data_shrinks(make_grid):
    grid, _ = make_grid()
    grid.selected = 2
    grid.set_data(["A"], [["x"]], [100], ["w"])
    assert grid.selected is None
    grid.selected = 0
    grid.set_data(["A"], [["x"], ["y"]], [100], ["w"])
    assert grid.selected == 0

# which column / which edge is under the mouse
def test_column_at_and_edge_at(make_grid):
    grid, _ = make_grid(widths=[100, 150])
    assert grid.column_at(0) == 0 and grid.column_at(99) == 0 and grid.column_at(100) == 1
    assert grid.column_at(249) == 1 and grid.column_at(250) is None and grid.column_at(-1) is None
    assert grid.edge_at(100) == 0 and grid.edge_at(100 + HANDLE) == 0 and grid.edge_at(100 + HANDLE + 1) is None
    assert grid.edge_at(250 - HANDLE) == 1 and grid.edge_at(50) is None

# no data: nothing is under the mouse
def test_column_at_with_no_data(make_grid):
    grid, _ = make_grid()
    grid.clear()
    grid._redraw()
    assert grid.column_at(5) is None and grid.edge_at(5) is None and grid.drawn == []

# clicking a heading sorts, but only when the mouse goes down and up on the same heading
def test_clicking_a_heading_sorts_by_it(make_grid):
    grid, calls = make_grid(widths=[100, 100])
    grid._on_header_press(Click(x=150))
    grid._on_header_release(Click(x=150))
    assert calls["sort"] == [1]
    grid._on_header_press(Click(x=50))
    grid._on_header_release(Click(x=150))                         # dragged onto another heading: not a click
    assert calls["sort"] == [1]

# a click on the very edge starts a resize, not a sort
def test_pressing_on_an_edge_does_not_sort(make_grid):
    grid, calls = make_grid(widths=[100, 100])
    grid._on_header_press(Click(x=101))
    grid._on_header_release(Click(x=101))
    assert calls["sort"] == []

# dragging an edge widens the column live, and reports the width once, when you let go
def test_dragging_an_edge_resizes_and_reports_on_release(make_grid):
    grid, calls = make_grid(widths=[100, 100])
    grid._on_header_press(Click(x=100))
    grid._on_header_drag(Click(x=130))
    assert grid.widths == [130, 100] and calls["resize"] == []
    grid._on_header_drag(Click(x=160))
    grid._on_header_release(Click(x=160))
    assert grid.widths == [160, 100] and calls["resize"] == [(0, 160)]
    assert grid._edges == [0, 160, 260]

# a column can't be dragged away to nothing
def test_dragging_cannot_go_below_the_minimum_width(make_grid):
    grid, calls = make_grid(widths=[100, 100])
    grid._on_header_press(Click(x=100))
    grid._on_header_drag(Click(x=-500))
    grid._on_header_release(Click(x=-500))
    assert grid.widths[0] == MIN_WIDTH and calls["resize"] == [(0, MIN_WIDTH)]

# pressing and releasing on an edge without moving reports nothing
def test_an_edge_press_without_a_drag_reports_nothing(make_grid):
    grid, calls = make_grid(widths=[100, 100])
    grid._on_header_press(Click(x=100))
    grid._on_header_release(Click(x=100))
    assert calls["resize"] == []

# a drag that did not start on an edge changes nothing
def test_dragging_elsewhere_in_the_header_does_not_resize(make_grid):
    grid, _ = make_grid(widths=[100, 100])
    grid._on_header_press(Click(x=50))
    grid._on_header_drag(Click(x=90))
    assert grid.widths == [100, 100]

# widening a column shows more of the cut text
def test_widening_a_column_shows_more_of_its_text(make_grid):
    grid, _ = make_grid(headers=("A",), rows=[("hello world, this is long",)], widths=[80])
    short = grid.drawn[0][2]
    grid.set_column_width(0, 400)
    grid._redraw()
    assert grid.drawn[0][2] == "hello world, this is long" and len(short) < len(grid.drawn[0][2])

# setting the width a column already has does nothing
def test_set_column_width_to_the_same_value_is_a_no_op(make_grid):
    grid, _ = make_grid(widths=[100, 100])
    grid._cache[0][0] = "marker"
    grid.set_column_width(0, 100)
    assert grid._cache[0][0] == "marker"

# the cursor turns into a resize arrow near an edge
def test_the_cursor_changes_near_an_edge(make_grid):
    grid, _ = make_grid(widths=[100, 100])
    grid._on_header_motion(Click(x=100))
    assert str(grid.header.cget("cursor")) == "sb_h_double_arrow"
    grid._on_header_motion(Click(x=50))
    assert str(grid.header.cget("cursor")) == ""

# right-clicking a heading says which column and where on the screen
def test_right_click_on_a_heading_reports_the_column_and_position(make_grid):
    grid, calls = make_grid(widths=[100, 100])
    grid._on_header_right_click(Click(x=150, x_root=11, y_root=22))
    assert calls["menu"] == [(1, 11, 22)]
    grid._on_header_right_click(Click(x=500))                     # past the last column
    assert len(calls["menu"]) == 1

# the mouse wheel scrolls three rows per notch, Shift + wheel scrolls sideways
def test_wheel_scrolls_rows_and_shift_wheel_scrolls_sideways(make_grid):
    rows = [[f"r{r}c{c}" for c in range(30)] for r in range(100)]
    grid, _ = make_grid(headers=[f"H{c}" for c in range(30)], rows=rows, widths=[100] * 30, aligns=["w"] * 30)
    assert grid._on_wheel(Click(delta=-120)) == "break"
    assert grid.body.canvasy(0) == 3 * grid.row_height
    grid._on_wheel(Click(delta=120))
    assert grid.body.canvasy(0) == 0
    assert grid._on_shift_wheel(Click(delta=-120)) == "break"
    grid.update_idletasks()                                       # Tk tells the headings at idle time
    assert grid.body.canvasx(0) > 0
    assert grid.header.canvasx(0) == grid.body.canvasx(0)         # the headings follow

# Shift + wheel and the arrow keys move one whole column at a time
def test_sideways_scrolling_lands_on_column_edges(make_grid):
    rows = [[f"r{r}c{c}" for c in range(30)] for r in range(10)]
    widths = [100 + 10 * c for c in range(30)]
    grid, _ = make_grid(headers=[f"H{c}" for c in range(30)], rows=rows, widths=widths, aligns=["w"] * 30)
    grid._on_shift_wheel(Click(delta=-120))
    assert grid.body.canvasx(0) == widths[0]
    grid._on_key(("x", 1))
    assert grid.body.canvasx(0) == widths[0] + widths[1]
    grid._on_shift_wheel(Click(delta=120))
    assert grid.body.canvasx(0) == widths[0]
    grid._on_key(("x", -1))
    assert grid.body.canvasx(0) == 0
    grid._on_key(("x", -1))                                       # already at the start: stays put
    assert grid.body.canvasx(0) == 0

def test_going_left_from_the_middle_of_a_column_snaps_to_its_start(make_grid):
    rows = [[f"r{r}c{c}" for c in range(30)] for r in range(10)]
    grid, _ = make_grid(headers=[f"H{c}" for c in range(30)], rows=rows, widths=[100] * 30, aligns=["w"] * 30)
    grid.body.xview_scroll(250, "units")                          # part-way into column 2
    grid._on_key(("x", -1))
    assert grid.body.canvasx(0) == 200
    grid.body.xview_scroll(50, "units")
    grid._on_key(("x", 1))
    assert grid.body.canvasx(0) == 300

# small wheel movements (touchpads) still move at least one notch
def test_small_wheel_deltas_count_as_one_notch(make_grid):
    assert GridView._notches(Click(delta=-30)) == 1
    assert GridView._notches(Click(delta=30)) == -1
    assert GridView._notches(Click(delta=-240)) == 2

# arrow keys and Page Up / Page Down scroll
def test_keys_scroll_the_grid(make_grid):
    rows = [[f"r{r}c{c}" for c in range(30)] for r in range(100)]
    grid, _ = make_grid(headers=[f"H{c}" for c in range(30)], rows=rows, widths=[100] * 30, aligns=["w"] * 30)
    assert grid._on_key(("y", 1)) == "break"
    assert grid.body.canvasy(0) == grid.row_height
    grid._on_key(("y", -1))
    assert grid.body.canvasy(0) == 0
    grid._on_key(("x", 1))
    assert grid.body.canvasx(0) > 0
    grid._on_key(("x", -1))
    assert grid.body.canvasx(0) == 0
    grid.winfo_toplevel().deiconify()                             # a page is 'one window high': needs a real size
    grid.update()
    grid._on_key(("page", 1))
    assert grid.body.canvasy(0) > 0

# new data keeps your place, and scroll_to_left goes back to the start
def test_set_data_keeps_the_scroll_position_and_scroll_to_left_resets_it(make_grid):
    rows = [[f"r{r}c{c}" for c in range(30)] for r in range(100)]
    grid, _ = make_grid(headers=[f"H{c}" for c in range(30)], rows=rows, widths=[100] * 30, aligns=["w"] * 30)
    grid.body.yview_scroll(10, "units")
    grid.set_data(grid.headers, rows, grid.widths, grid.aligns)
    assert grid.body.canvasy(0) == 10 * grid.row_height
    grid.scroll_to_left()
    assert grid.body.canvasy(0) == 0 and grid.body.canvasx(0) == 0

# the scroll area matches the data, and clearing empties everything
def test_scroll_area_follows_the_data_and_clear_empties_it(make_grid):
    grid, _ = make_grid(widths=[100, 150])
    assert str(grid.body.cget("scrollregion")) == f"0 0 250 {3 * grid.row_height}"
    grid.clear()
    grid._redraw()
    assert grid.rows == [] and grid.headers == [] and grid.drawn == []
    assert str(grid.body.cget("scrollregion")) == "0 0 1 1"

# a theme change reloads the colours without breaking the grid
def test_a_theme_change_redraws_with_the_new_colours(make_grid):
    grid, _ = make_grid()
    grid.c_body = "#123456"
    grid._on_theme_changed()
    assert grid.c_body != "#123456"
    grid._redraw()
    assert len(grid.drawn) == 6

# the grid draws nothing (and doesn't crash) when it has no rows
def test_a_grid_with_headings_but_no_rows_draws_no_cells(make_grid):
    grid, _ = make_grid(rows=[])
    assert grid.drawn == [] and grid.heading_texts() == ["Name", "Price"]

# the row that is cut off at the bottom of the drawn area is included too
def test_the_partly_visible_last_row_is_drawn(make_grid):
    rows = [[f"r{r}"] for r in range(500)]
    grid, _ = make_grid(headers=["A"], rows=rows, widths=[100], aligns=["w"])
    assert {r for r, _, _ in grid.drawn} == set(range(int(800 // grid.row_height) + 1))

# the selected row is painted in the selection colour, the others are not
def test_the_selected_row_is_painted_in_the_selection_colour(make_grid):
    grid, _ = make_grid()
    grid.selected = 1
    grid._redraw()
    fills = [grid.body.itemcget(i, "fill") for i in grid.body.find_all() if grid.body.type(i) == "rectangle"]
    assert fills.count(grid.c_select) == 1 and len(fills) == 3

# clicking after scrolling picks the row under the mouse, not the one at the top of the data
def test_clicking_after_scrolling_selects_the_row_under_the_mouse(make_grid):
    rows = [[f"r{r}"] for r in range(100)]
    grid, _ = make_grid(headers=["A"], rows=rows, widths=[100], aligns=["w"])
    grid.body.yview_scroll(10, "units")
    grid._on_body_click(Click(y=3))
    assert grid.selected == 10

# the highlight survives new data that is still long enough, and goes when the row is gone
def test_the_selection_is_dropped_exactly_when_its_row_is_gone(make_grid):
    grid, _ = make_grid()
    grid.selected = 1
    grid.set_data(["A"], [["x"], ["y"]], [100], ["w"])
    assert grid.selected == 1
    grid.set_data(["A"], [["x"]], [100], ["w"])
    assert grid.selected is None

# the heading colour is close to the body colour (so it stays readable) and never equals the text colour
def test_the_heading_colours_stay_readable(make_grid):
    grid, _ = make_grid()
    assert grid.c_head != grid.c_head_text
    assert grid.c_head_text == grid.c_text
    assert grid.c_head == blend(grid.c_body, grid.c_text, 0.12)

# the heading colour follows a theme change
def test_the_heading_colour_follows_the_theme(app, make_grid):
    grid, _ = make_grid()
    style = grid.winfo_toplevel().tk.call("ttk::style", "theme", "use")
    import ttkbootstrap as ttk
    colors = ttk.Style().colors
    assert grid.header.cget("bg") == grid.c_head == blend(colors.inputbg, colors.inputfg, 0.12)

# closing a grid frees its bold font on the spot, instead of leaving it for the garbage collector
# (which may run on a worker thread, where touching Tk can hang)
def test_destroying_a_grid_deletes_its_bold_font_right_away(app):
    import ttkbootstrap as ttk
    top = ttk.Toplevel(master=app)
    top.withdraw()
    grid = GridView(top)
    name = grid.bold.name
    assert name in app.tk.call("font", "names")
    top.destroy()
    assert name not in app.tk.call("font", "names")
    assert grid.bold.delete_font is False