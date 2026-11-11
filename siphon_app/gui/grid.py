"""
siphon_app/gui/grid.py

The data grid in the preview: column headings on top, rows underneath, and scroll bars.

Why not tkinter's own Treeview? On Windows it redraws the whole grid on every pixel of a
sideways scroll, which gets very laggy with wide tables. This grid draws on a Canvas and
only draws the cells you can actually see, so scrolling stays smooth however big the table is.

It only knows how to show text. Sorting, searching and the menus are done by whoever uses
it, through the callbacks passed to GridView().
"""
import tkinter as tk
import tkinter.font as tkfont
from bisect import bisect_right
from collections.abc import Callable

import ttkbootstrap as ttk

PAD = 8                 # space on each side of the text in a cell
MIN_WIDTH = 40          # a column can't be dragged narrower than this
HANDLE = 5              # how close (in pixels) to a heading's right edge counts as 'the edge'
WHEEL_ROWS = 3          # rows moved by one notch of the mouse wheel
WHEEL_COLUMNS = 1       # columns moved by one notch of Shift + wheel
FALLBACK_SIZE = (800, 400)      # how much to draw when the grid is not on screen yet (tests)
ARROW_UP, ARROW_DOWN = " ^", " v"    # sort arrows: plain characters, every font has them

def blend(color_a: str, color_b: str, share: float) -> str:
    """A colour `share` of the way from a to b (both '#rrggbb'). Used for the row stripes."""
    a = [int(color_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(color_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * share):02x}" for x, y in zip(a, b))

def shorten(text: str, room: int, measure: Callable[[str], int]) -> str:
    """Cut text so it fits in `room` pixels, ending with an ellipsis if it had to be cut."""
    if not text or measure(text) <= room:
        return text
    low, high = 0, len(text)
    while low < high:                                   # binary search for the longest piece that fits
        middle = (low + high + 1) // 2
        if measure(text[:middle] + "…") <= room:
            low = middle
        else:
            high = middle - 1
    return text[:low] + "…"

class GridView(ttk.Frame):
    def __init__(self, master,
                on_sort: Callable[[int], None] | None = None,
                on_menu: Callable[[int, int, int], None] | None = None,
                on_resize: Callable[[int, int], None] | None = None) -> None:
        super().__init__(master)
        self.on_sort = on_sort or (lambda column: None)             # heading clicked
        self.on_menu = on_menu or (lambda column, x, y: None)       # heading right-clicked (column, screen x, y)
        self.on_resize = on_resize or (lambda column, width: None)  # heading edge dragged (column, new width)

        self._x_seen: tuple = ()   # last sideways position the scroll bar was given
        self._y_seen: tuple = ()   # same for up and down
        self.headers: list[str] = []
        self.rows: list[list[str]] = []                 # the text of every row shown
        self.widths: list[int] = []
        self.aligns: list[str] = []                     # "w" (left) or "e" (right) per column
        self.sort_column: int | None = None
        self.sort_descending = False
        self.selected: int | None = None                # the highlighted row
        self.drawn: list[tuple[int, int, str]] = []     # (row, column, text) of the cells drawn last time

        self._box: tuple[float, float, float, float] | None = None     # canvas area drawn last time
        self._edges = [0]                               # x of each column's left edge, plus the far right edge
        self._cache: list[dict[int, str]] = []          # per column: row -> text cut to fit
        self._redraw_job = None
        self._resizing: tuple[int, int, int] | None = None      # (column, mouse x at start, width at start)
        self._moved = False                             # did the mouse move since the press? (click vs drag)
        self._press_column: int | None = None           # the heading the mouse went down on

        self.font = tkfont.nametofont("TkDefaultFont")
        self.bold = self.font.copy()
        self.bold.configure(weight="bold")
        self.row_height = self.font.metrics("linespace") + 10
        self.header_height = self.row_height + 4

        # the pieces: headings, body, and the two scroll bars
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.header = tk.Canvas(self, height=self.header_height, highlightthickness=0, bd=0)
        self.header.grid(row=0, column=0, sticky="ew")
        self.body = tk.Canvas(self, highlightthickness=0, bd=0, takefocus=1,
                            xscrollincrement=1, yscrollincrement=self.row_height)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.body.yview)
        self.vbar.grid(row=1, column=1, sticky="ns")
        self.hbar = ttk.Scrollbar(self, orient="horizontal", command=self._xview)
        self.hbar.grid(row=2, column=0, sticky="ew")
        self.header.configure(xscrollincrement=1)
        self.body.configure(xscrollcommand=self._on_xscrolled, yscrollcommand=self._on_yscrolled)

        self._load_colors()
        self.bind("<<ThemeChanged>>", self._on_theme_changed)
        self.body.bind("<Configure>", lambda event: self._invalidate())
        self.body.bind("<Button-1>", self._on_body_click)
        self.body.bind("<Enter>", lambda event: self.body.focus_set())      # so the wheel and keys reach it
        for widget in (self.body, self.header):
            widget.bind("<MouseWheel>", self._on_wheel)
            widget.bind("<Shift-MouseWheel>", self._on_shift_wheel)
        for key, action in (("<Left>", ("x", -1)), ("<Right>", ("x", 1)),
                            ("<Up>", ("y", -1)), ("<Down>", ("y", 1)),
                            ("<Prior>", ("page", -1)), ("<Next>", ("page", 1))):
            self.body.bind(key, lambda event, a=action: self._on_key(a))
        self.header.bind("<Motion>", self._on_header_motion)
        self.header.bind("<ButtonPress-1>", self._on_header_press)
        self.header.bind("<B1-Motion>", self._on_header_drag)
        self.header.bind("<ButtonRelease-1>", self._on_header_release)
        self.header.bind("<Button-3>", self._on_header_right_click)

    #what the person of this class uses
    def destroy(self) -> None:
        """Close the grid and give its bold font back right now.

        A Font cleans itself up when Python collects it, and that can happen on any thread, such
        as an export's worker thread, where touching Tk can hang. Doing it here keeps it on the
        window's own thread.
        """
        super().destroy()
        if self.bold.delete_font:
            self.bold.delete_font = False               # so the later clean-up has nothing left to do
            try:
                self.tk.call("font", "delete", self.bold.name)
            except tk.TclError:                         # the window is already gone: nothing to free
                pass

    def set_data(self, headers: list[str], rows: list[list[str]], widths: list[int],
                aligns: list[str], sort_column: int | None = None,
                sort_descending: bool = False) -> None:
        """Show this data. Keeps the scroll position, so searching or sorting doesn't jump around."""
        self.headers, self.rows = list(headers), rows
        self.widths, self.aligns = list(widths), list(aligns)
        self.sort_column, self.sort_descending = sort_column, sort_descending
        if self.selected is not None and self.selected >= len(rows):
            self.selected = None
        self._cache = [{} for _ in self.widths]
        self._layout()

    def clear(self) -> None:
        self.set_data([], [], [], [])

    def heading_texts(self) -> list[str]:
        """The headings as drawn, with the sort arrow."""
        return [self._heading_text(column) for column in range(len(self.headers))]

    def scroll_to_left(self) -> None:
        self.body.xview_moveto(0)
        self.body.yview_moveto(0)

    #sizes and colours
    def _load_colors(self) -> None:
        """Pick the colours from the current ttkbootstrap theme."""
        colors = ttk.Style().colors
        self.c_body, self.c_text = colors.inputbg, colors.inputfg
        self.c_stripe = blend(colors.inputbg, colors.border, 0.25)
        # The heading is the body colour nudged toward the text colour, so it is a little darker in a
        # light theme and a little lighter in a dark one, and the text on it always stays readable.
        self.c_head, self.c_head_text = blend(colors.inputbg, colors.inputfg, 0.12), colors.inputfg
        self.c_line = colors.border
        self.c_select, self.c_select_text = colors.selectbg, colors.selectfg
        self.header.configure(bg=self.c_head)
        self.body.configure(bg=self.c_body)

    def _on_theme_changed(self, event=None) -> None:
        self._load_colors()
        self._draw_header()
        self._invalidate()

    def _layout(self) -> None:
        """The data or the widths changed: recompute the edges and scroll area, then redraw."""
        self._edges = [0]
        for width in self.widths:
            self._edges.append(self._edges[-1] + width)
        total_width = max(self._edges[-1], 1)
        self.body.configure(scrollregion=(0, 0, total_width, max(len(self.rows) * self.row_height, 1)))
        self.header.configure(scrollregion=(0, 0, total_width, self.header_height))
        self._draw_header()
        self.header.xview_moveto(self.body.xview()[0])
        self._invalidate()

    #drawing
    def _heading_text(self, column: int) -> str:
        arrow = ""
        if column == self.sort_column:
            arrow = ARROW_DOWN if self.sort_descending else ARROW_UP
        return self.headers[column] + arrow

    def _draw_header(self) -> None:
        """Draw every heading (there are at most a few hundred, so no need to be clever)."""
        h = self.header
        h.delete("all")
        for column in range(len(self.headers)):
            left, right = self._edges[column], self._edges[column + 1]
            text = shorten(self._heading_text(column), self.widths[column] - 2 * PAD, self.bold.measure)
            h.create_text(left + PAD, self.header_height / 2, text=text, anchor="w",
                        fill=self.c_head_text, font=self.bold)
            h.create_line(right - 1, 4, right - 1, self.header_height - 4, fill=self.c_line)
        h.create_line(0, self.header_height - 1, max(self._edges[-1], 1), self.header_height - 1,
                    fill=self.c_line)

    def _schedule_redraw(self) -> None:
        """Redraw once things go quiet. Dragging a scroll bar fires many events; one redraw is enough."""
        if self._redraw_job is None:
            self._redraw_job = self.after_idle(self._redraw)

    def _invalidate(self) -> None:
        """What is drawn is out of date (new data, new size, new colours): redraw for sure."""
        self._box = None
        self._schedule_redraw()

    def _view_size(self) -> tuple[int, int]:
        """The size of the visible part of the body (a fixed guess while it is not on screen yet)."""
        width, height = self.body.winfo_width(), self.body.winfo_height()
        return (width, height) if width > 1 else FALLBACK_SIZE

    def _scrolled(self) -> None:
        """
        The view moved. We draw a bit more than is visible (one extra screen on every side), and
        Tk slides those already-drawn items around by itself, which is fast. So we only redraw
        when the view is about to run out of drawn cells.
        """
        if self._box is None:
            self._schedule_redraw()
            return
        view_w, view_h = self._view_size()
        x0, y0 = self.body.canvasx(0), self.body.canvasy(0)
        left, top, right, bottom = self._box
        total_w, total_h = self._edges[-1], len(self.rows) * self.row_height
        if (x0 < left or y0 < top or min(x0 + view_w, total_w) > right
                or min(y0 + view_h, total_h) > bottom):
            self._schedule_redraw()

    def _fit(self, row: int, column: int) -> str:
        """The text of one cell, cut to the column width (remembered, because measuring is slow)."""
        cache = self._cache[column]
        if row not in cache:
            cache[row] = shorten(self.rows[row][column], self.widths[column] - 2 * PAD, self.font.measure)
        return cache[row]

    def _redraw(self) -> None:
        """Draw the cells around the visible area (the visible part plus one extra screen on each side)."""
        self._redraw_job = None
        b = self.body
        b.delete("all")
        self.drawn = []
        self._box = None
        if not self.rows or not self.widths:
            return
        view_w, view_h = self._view_size()
        x0, y0 = b.canvasx(0), b.canvasy(0)
        rh = self.row_height
        total_w, total_h = self._edges[-1], len(self.rows) * rh

        # the area to draw: the view plus one screen each way, kept inside the data
        left, right = max(0.0, x0 - view_w), min(float(total_w), x0 + 2 * view_w)
        top, bottom = max(0.0, y0 - view_h), min(float(total_h), y0 + 2 * view_h)
        first_row = int(top // rh)
        last_row = min(len(self.rows), int(bottom // rh) + 1)
        first_col = max(0, min(bisect_right(self._edges, left) - 1, len(self.widths) - 1))
        last_col = first_col
        while last_col < len(self.widths) and self._edges[last_col] < right:
            last_col += 1
        # remember what we covered, but only up to the edge of the last drawn row and column
        self._box = (self._edges[first_col], first_row * rh, self._edges[last_col], last_row * rh)

        for row in range(first_row, last_row):
            y = row * rh
            if row == self.selected:
                fill, text_color = self.c_select, self.c_select_text
            else:
                fill, text_color = (self.c_stripe if row % 2 else self.c_body), self.c_text
            b.create_rectangle(self._edges[first_col], y, self._edges[last_col], y + rh, fill=fill, outline="")
            for column in range(first_col, last_col):
                text = self._fit(row, column)
                self.drawn.append((row, column, text))
                if not text:
                    continue
                cell_left, cell_right = self._edges[column], self._edges[column + 1]
                if self.aligns[column] == "e":
                    b.create_text(cell_right - PAD, y + rh / 2, text=text, anchor="e", fill=text_color, font=self.font)
                else:
                    b.create_text(cell_left + PAD, y + rh / 2, text=text, anchor="w", fill=text_color, font=self.font)
        for column in range(first_col, last_col):                   # thin lines between the columns
            x = self._edges[column + 1] - 1
            b.create_line(x, first_row * rh, x, last_row * rh, fill=self.c_line)

    #scrolling
    def _xview(self, *args) -> None:
        self.body.xview(*args)

    def _on_xscrolled(self, first, last) -> None:
        """The body scrolled sideways: move the scroll bar and the headings with it."""
        # the canvas reports this on every vertical step too, and a scroll bar
        # redraw is slow on Windows, so only touch things when it really moved
        if (first, last) != self._x_seen:
            self._x_seen = (first, last)
            self.hbar.set(first, last)
            self.header.xview_moveto(first)
        self._scrolled()

    def _on_yscrolled(self, first, last) -> None:
        if (first, last) != self._y_seen:
            self._y_seen = (first, last)
            self.vbar.set(first, last)
        self._scrolled()

    def _on_wheel(self, event) -> str:
        self.body.yview_scroll(self._notches(event) * WHEEL_ROWS, "units")
        return "break"

    def _on_shift_wheel(self, event) -> str:
        self._scroll_columns(self._notches(event) * WHEEL_COLUMNS)
        return "break"

    def _scroll_columns(self, count: int) -> None:
        """Move sideways by whole columns so a column always lines up with the left edge."""
        if not self.widths:
            return
        x0 = self.body.canvasx(0)
        index = bisect_right(self._edges, x0 + 0.5) - 1          # the column at the left edge
        if count < 0 and x0 > self._edges[index] + 0.5:
            count += 1                                           # part-way into a column: going left snaps to its start
        target = min(max(index + count, 0), len(self.widths) - 1)
        self.body.xview_moveto(self._edges[target] / self._edges[-1])

    @staticmethod
    def _notches(event) -> int:
        """Mouse wheel amount as whole notches (Windows reports 120 per notch; always move at least one)."""
        steps = int(-event.delta / 120)
        return steps or (-1 if event.delta > 0 else 1)

    def _on_key(self, action: tuple[str, int]) -> str:
        kind, direction = action
        if kind == "x":
            self._scroll_columns(direction)
        elif kind == "y":
            self.body.yview_scroll(direction, "units")
        else:
            self.body.yview_scroll(direction, "pages")
        return "break"

    #clicking the body
    def _on_body_click(self, event) -> None:
        """Highlight the clicked row."""
        row = int(self.body.canvasy(event.y) // self.row_height)
        self.selected = row if 0 <= row < len(self.rows) else None
        self.body.focus_set()
        self._invalidate()

    #the headings: sorting, the menu and resizing
    def column_at(self, x: float) -> int | None:
        """Which column is at this canvas x position (None if it is past the last one)."""
        if not self.widths or x < 0 or x >= self._edges[-1]:
            return None
        return bisect_right(self._edges, x) - 1

    def edge_at(self, x: float) -> int | None:
        """The column whose RIGHT edge is within a few pixels of x, if any (the resize handle)."""
        for column in range(len(self.widths)):
            if abs(x - self._edges[column + 1]) <= HANDLE:
                return column
        return None

    def _on_header_motion(self, event) -> None:
        near_edge = self.edge_at(self.header.canvasx(event.x)) is not None
        self.header.configure(cursor="sb_h_double_arrow" if near_edge else "")

    def _on_header_press(self, event) -> None:
        x = self.header.canvasx(event.x)
        self._moved = False
        edge = self.edge_at(x)
        self._resizing = (edge, event.x, self.widths[edge]) if edge is not None else None
        self._press_column = self.column_at(x)

    def _on_header_drag(self, event) -> None:
        if self._resizing is None:
            return
        column, start_x, start_width = self._resizing
        self._moved = True
        self.set_column_width(column, start_width + event.x - start_x)

    def _on_header_release(self, event) -> None:
        if self._resizing is not None:
            column = self._resizing[0]
            self._resizing = None
            if self._moved:
                self.on_resize(column, self.widths[column])
            return
        if self._press_column is not None and self._press_column == self.column_at(self.header.canvasx(event.x)):
            self.on_sort(self._press_column)

    def set_column_width(self, column: int, width: int) -> None:
        """Make one column wider or narrower (never below MIN_WIDTH)."""
        width = max(MIN_WIDTH, int(width))
        if width == self.widths[column]:
            return
        self.widths[column] = width
        self._cache[column] = {}                    # the cut-to-fit texts of that column are stale now
        self._layout()

    def _on_header_right_click(self, event) -> None:
        column = self.column_at(self.header.canvasx(event.x))
        if column is not None:
            self.on_menu(column, event.x_root, event.y_root)