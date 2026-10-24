"""
siphon_app/gui/table_view.py

The middle of the window: a list of the tables found (with tick boxes) on the left,
and a preview of the selected table on the right, with search, click-to-sort
columns and a Copy button.
"""
import tkinter.font as tkfont
from collections.abc import Callable

import ttkbootstrap as ttk

from siphon_app.core.cleaner import parse_number
from siphon_app.core.models import Cell, Table

MAX_PREVIEW_ROWS = 1000 # a window can't usefully show more, and drawing 30,000 rows is slow
SEARCH_DELAY_MS = 200  # wait for a pause in typing before filtering
LIST_WIDTH = 300  # width of the table list, in pixels
# Plain characters on purpose: symbols like a tick or an arrow show up as empty boxes on
# computers whose fonts don't have them.
CHECKED, UNCHECKED = "[x]", "[ ]"
ARROW_UP, ARROW_DOWN = " ^", " v"
PLACEHOLDER = "Tables will show up here."

def display(cell: Cell) -> str:
    return "" if cell is None else str(cell)

def size_text(table: Table) -> str:
    return f"{table.n_rows:,} \u00d7 {table.n_cols}"

def filter_rows(rows: list[list[Cell]], query: str) -> list[list[Cell]]:
    """Rows containing every word of the query (any column, ignoring capitals)."""
    words = query.lower().split()
    if not words:
        return rows
    kept = []
    for row in rows:
        text = " ".join(display(cell) for cell in row).lower()
        if all(word in text for word in words):
            kept.append(row)
    return kept

def _sort_key(cell: Cell) -> tuple:
    """Numbers (even '$1,234' or '12%') sort by value and come before text."""
    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
        return (0, float(cell), "")
    text = display(cell)
    parsed = parse_number(text)
    if parsed is not None:
        return (0, float(parsed.value), "")
    return (1, 0.0, text.lower())

def sort_rows(rows: list[list[Cell]], column: int, descending: bool = False) -> list[list[Cell]]:
    """Sort by one column. Blank cells always go last, whichever way you sort."""
    filled = [row for row in rows if display(row[column]).strip() != ""]
    blank = [row for row in rows if display(row[column]).strip() == ""]
    filled.sort(key=lambda row: _sort_key(row[column]), reverse=descending)
    return filled + blank

def rows_to_tsv(headers: list[str], rows: list[list[Cell]]) -> str:
    """Tab-separated text that pastes straight into Excel."""
    def clean(cell: Cell) -> str:
        return display(cell).replace("\t", " ").replace("\r", " ").replace("\n", " ")
    lines = ["\t".join(clean(h) for h in headers)]
    lines += ["\t".join(clean(cell) for cell in row) for row in rows]
    return "\n".join(lines) + "\n"

def is_numeric_column(rows: list[list[Cell]], column: int) -> bool:
    """True if most of the first rows of this column are numbers (so we right-align them)."""
    sample = [row[column] for row in rows[:200] if display(row[column]).strip() != ""]
    if not sample:
        return False
    numbers = sum(1 for cell in sample if _sort_key(cell)[0] == 0)
    return numbers / len(sample) >= 0.8

#the widget
class TableView(ttk.Frame):
    def __init__(self, master, notify: Callable[[str], None] | None = None) -> None:
        super().__init__(master)
        self.notify = notify or (lambda text: None) # how we send a message to the status bar

        self._tables: list[Table] = []
        self._checked: set[int] = set() # indexes of the ticked tables
        self._visible: list[int] = [] # indexes shown in the list
        self._current: int | None = None # the table being previewed
        self._shown_rows: list[list[Cell]] = [] # rows matching the search (all of them)
        self._sort_column: int | None = None
        self._sort_descending = False
        self._search_job = None

        self.bold = tkfont.nametofont("TkDefaultFont").copy()# the normal font, but bold
        self.bold.configure(weight="bold")

        self.hide_layout = ttk.BooleanVar(value=True)
        self.search_var = ttk.StringVar()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self._build_placeholder()
        self._build_main()
        self.set_tables([])

#building widgets
    def _build_placeholder(self) -> None:
        self.placeholder = ttk.Label(self, text=PLACEHOLDER, bootstyle="secondary",
                                    anchor="center", justify="center")
        self.placeholder.grid(row=0, column=0, sticky="nsew")

    def _build_main(self) -> None:
        self.main = ttk.Frame(self)
        self.main.grid(row=0, column=0, sticky="nsew")
        self.main.columnconfigure(1, weight=1)
        self.main.rowconfigure(0, weight=1)

        #left, the list of tables
        left = ttk.Frame(self.main, width=LIST_WIDTH)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        left.grid_propagate(False) # keep it exactly LIST_WIDTH wide
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        self.list_title = ttk.Label(left, text="Tables found", font=self.bold)
        self.list_title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        self.table_list = ttk.Treeview(left, columns=("use", "name", "size"), show="headings",
                                    selectmode="browse")
        self.table_list.heading("use", text="")
        self.table_list.heading("name", text="Table")
        self.table_list.heading("size", text="Rows \u00d7 cols")
        self.table_list.column("use", width=40, stretch=False, anchor="center")
        self.table_list.column("name", width=150)
        self.table_list.column("size", width=90, stretch=False, anchor="e")
        self.table_list.grid(row=1, column=0, sticky="nsew")
        list_scroll = ttk.Scrollbar(left, orient="vertical", command=self.table_list.yview)
        list_scroll.grid(row=1, column=1, sticky="ns")
        self.table_list.configure(yscrollcommand=list_scroll.set)
        self.table_list.bind("<<TreeviewSelect>>", self._on_list_select)
        self.table_list.bind("<Button-1>", self._on_list_click)
        self.table_list.bind("<space>", self._on_space)

        self.hint_label = ttk.Label(left, text="", bootstyle="secondary", wraplength=LIST_WIDTH - 10,
                                    justify="left")
        self.hint_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        ttk.Checkbutton(left, text="Hide layout tables", variable=self.hide_layout,
                        command=self._refresh_list).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        buttons = ttk.Frame(left)
        buttons.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(buttons, text="Select all", bootstyle="secondary-outline",
                command=self.select_all).pack(side="left")
        ttk.Button(buttons, text="Select none", bootstyle="secondary-outline",
                command=self.select_none).pack(side="left", padx=(8, 0))

        # -- right: the preview
        right = ttk.Frame(self.main)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        head = ttk.Frame(right)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        head.columnconfigure(0, weight=1)
        self.name_label = ttk.Label(head, text="", font=self.bold, anchor="w")
        self.name_label.grid(row=0, column=0, sticky="ew")
        self.size_label = ttk.Label(head, text="", bootstyle="secondary")
        self.size_label.grid(row=0, column=1, padx=(8, 0))

        tools = ttk.Frame(right)
        tools.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        tools.columnconfigure(1, weight=1)
        ttk.Label(tools, text="Search").grid(row=0, column=0, padx=(0, 8))
        self.search_entry = ttk.Entry(tools, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=1, sticky="ew")
        self.search_entry.bind("<KeyRelease>", self._on_search_key)
        self.copy_button = ttk.Button(tools, text="Copy", bootstyle="secondary-outline",
                                    command=self.copy_table)
        self.copy_button.grid(row=0, column=2, padx=(8, 0))

        self.preview = ttk.Treeview(right, show="headings", selectmode="extended")
        self.preview.grid(row=2, column=0, sticky="nsew")
        y_scroll = ttk.Scrollbar(right, orient="vertical", command=self.preview.yview)
        y_scroll.grid(row=2, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(right, orient="horizontal", command=self.preview.xview)
        x_scroll.grid(row=3, column=0, sticky="ew")
        self.preview.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.footer_label = ttk.Label(right, text="", bootstyle="secondary")
        self.footer_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

#public
    def set_tables(self, tables: list[Table], message: str = PLACEHOLDER) -> None:
        """Show a new set of tables (or the placeholder, if there are none)."""
        self._tables = list(tables)
        self._checked = {i for i, table in enumerate(self._tables) if not table.is_layout}
        self._current = None
        self._reset_preview_controls()
        if not self._tables:
            self.placeholder.configure(text=message)
            self.placeholder.tkraise()
            self._visible = []
            self.table_list.delete(*self.table_list.get_children()) # don't leave the old list behind
            self.list_title.configure(text="Tables found")
            self.hint_label.configure(text="")
            self._clear_preview()
            return
        self.main.tkraise()
        self._refresh_list()

    def checked_tables(self) -> list[Table]:
        """The tables that are ticked and visible, in page order. (Step 9 exports these.)"""
        return [self._tables[i] for i in self._visible if i in self._checked]

    def select_all(self) -> None:
        self._checked |= set(self._visible)
        self._redraw_checks()

    def select_none(self) -> None:
        self._checked -= set(self._visible)
        self._redraw_checks()

    def toggle(self, index: int) -> None:
        self._checked ^= {index} # add it if missing, remove it if there
        self._redraw_checks()

    def copy_table(self) -> None:
        """Copy every row matching the search (not just the visible ones) for pasting into Excel."""
        if self._current is None:
            return
        table = self._tables[self._current]
        self.clipboard_clear()
        self.clipboard_append(rows_to_tsv(table.headers, self._shown_rows))
        self.notify(f"Copied {len(self._shown_rows):,} rows to the clipboard.")

#the list
    def _refresh_list(self) -> None:
        hide = self.hide_layout.get()
        self._visible = [i for i, t in enumerate(self._tables) if not (hide and t.is_layout)]
        hidden = len(self._tables) - len(self._visible)

        self.table_list.delete(*self.table_list.get_children())
        for index in self._visible:
            table = self._tables[index]
            glyph = CHECKED if index in self._checked else UNCHECKED
            self.table_list.insert("", "end", iid=str(index), values=(glyph, table.name, size_text(table)))
        self.list_title.configure(text=f"Tables found ({len(self._visible)})")

        if not self._visible:
            self.hint_label.configure(text=f"All {hidden} tables look like page layout. "
                                        "Untick \"Hide layout tables\" to see them.")
        elif hidden:
            word = "table" if hidden == 1 else "tables"
            self.hint_label.configure(text=f"{hidden} layout {word} hidden.")
        else:
            self.hint_label.configure(text="")

        if self._current not in self._visible:
            self._current = None
        target = self._current if self._current is not None else (self._visible[0] if self._visible else None)
        if target is None:
            self._clear_preview()
            return
        self.table_list.selection_set(str(target))
        self.table_list.focus(str(target))
        if self._current != target:
            self._current = target
            self._reset_preview_controls()
        self._render_preview()

    def _redraw_checks(self) -> None:
        for index in self._visible:
            glyph = CHECKED if index in self._checked else UNCHECKED
            self.table_list.set(str(index), "use", glyph)

    def _on_list_select(self, event=None) -> None:
        selected = self.table_list.selection()
        if not selected or int(selected[0]) == self._current:
            return
        self._current = int(selected[0])
        self._reset_preview_controls() # columns differ, so search and sort start over
        self._render_preview()

    def _on_list_click(self, event) -> str | None:
        if self.table_list.identify_region(event.x, event.y) == "cell" \
                and self.table_list.identify_column(event.x) == "#1":
            row = self.table_list.identify_row(event.y)
            if row:
                self.toggle(int(row))
                return "break" # ticking a box doesn't change the preview
        return None

    def _on_space(self, event=None) -> str:
        focused = self.table_list.focus()
        if focused:
            self.toggle(int(focused))
        return "break"

# the preview
    def _reset_preview_controls(self) -> None:
        self.search_var.set("")
        self._sort_column = None
        self._sort_descending = False

    def _clear_preview(self) -> None:
        self.name_label.configure(text="")
        self.size_label.configure(text="")
        self.footer_label.configure(text="")
        self.preview.delete(*self.preview.get_children())
        self.preview.configure(columns=())
        self._shown_rows = []

    def _render_preview(self) -> None:
        table = self._tables[self._current]
        rows = filter_rows(table.rows, self.search_var.get())
        if self._sort_column is not None:
            rows = sort_rows(rows, self._sort_column, self._sort_descending)
        self._shown_rows = rows

        self.name_label.configure(text=table.name)
        self.size_label.configure(text=f"{table.n_rows:,} rows \u00d7 {table.n_cols} columns")

        font = tkfont.nametofont("TkDefaultFont")
        ids = [str(i) for i in range(table.n_cols)]
        self.preview.delete(*self.preview.get_children())
        self.preview.configure(columns=ids)
        for column, header in enumerate(table.headers):
            arrow = ""
            if column == self._sort_column:
                arrow = ARROW_DOWN if self._sort_descending else ARROW_UP
            self.preview.heading(ids[column], text=header + arrow,
                                command=lambda c=column: self._sort_by(c))
            sample = [display(r[column]) for r in table.rows[:100]]
            width = max([font.measure(header + ARROW_UP)] + [font.measure(text) for text in sample]) + 24
            self.preview.column(ids[column], width=max(60, min(width, 320)), stretch=False,
                                anchor="e" if is_numeric_column(table.rows, column) else "w")
        for row in rows[:MAX_PREVIEW_ROWS]:
            self.preview.insert("", "end", values=[display(cell) for cell in row])

        if len(rows) > MAX_PREVIEW_ROWS:
            self.footer_label.configure(text=f"Showing the first {MAX_PREVIEW_ROWS:,} of {len(rows):,} rows. "
                                            "Copy and export still include every row.")
        elif self.search_var.get().strip():
            self.footer_label.configure(text=f"{len(rows):,} of {table.n_rows:,} rows match.")
        else:
            self.footer_label.configure(text="")

    def _sort_by(self, column: int) -> None:
        if column == self._sort_column:
            self._sort_descending = not self._sort_descending # second click reverses
        else:
            self._sort_column, self._sort_descending = column, False
        self._render_preview()

    def _on_search_key(self, event=None) -> None:
        if self._search_job is not None:
            self.after_cancel(self._search_job) # restarts the timer on every key press
        self._search_job = self.after(SEARCH_DELAY_MS, self._apply_search)

    def _apply_search(self) -> None:
        self._search_job = None
        if self._current is not None:
            self._render_preview()