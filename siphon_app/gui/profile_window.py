"""
siphon_app/gui/profile_window.py

A pop-up that summarises each column of the selected table: type, filled and empty
cells, different values, and for numbers the smallest, largest and average.
"""
import ttkbootstrap as ttk

from siphon_app.core.models import Table
from siphon_app.core.profile import ColumnProfile, NUMBER, profile_table

# What each column of the pop-up is called, and how wide it starts (in pixels).
HEADINGS = ("Column", "Type", "Filled", "Empty", "Different", "Smallest", "Largest", "Average",
            "Most common")
WIDTHS = (160, 70, 70, 70, 80, 90, 90, 90, 200)


def format_number(value: float | None) -> str:
    """1234.0 -> "1,234", 1234.567 -> "1,234.57", nothing -> "" (so empty cells stay blank)."""
    if value is None:
        return ""
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def profile_row(profile: ColumnProfile) -> tuple[str, ...]:
    """One column's profile as the strings the grid shows, in the same order as HEADINGS."""
    common = f"{profile.common} ({profile.common_count:,})" if profile.common_count else ""
    return (
        profile.name,
        profile.kind,
        f"{profile.filled:,}",
        f"{profile.empty:,}",
        f"{profile.unique:,}",
        format_number(profile.minimum),
        format_number(profile.maximum),
        format_number(profile.mean),
        common,
    )


def profile_rows(table: Table) -> list[tuple[str, ...]]:
    return [profile_row(p) for p in profile_table(table)]


def summary_text(table: Table) -> str:
    """The one-line summary above the grid."""
    profiles = profile_table(table)
    numbers = sum(1 for p in profiles if p.kind == NUMBER)
    empty_cells = sum(p.empty for p in profiles)
    return (f"{table.n_rows:,} rows, {table.n_cols} columns ({numbers} numeric). "
            f"{empty_cells:,} empty cells in total.")


class ProfileWindow(ttk.Toplevel):
    def __init__(self, master, table: Table) -> None:
        # master=master by name: ttkbootstrap's first positional argument is the title.
        super().__init__(title=f"Profile: {table.name}", size=(960, 360), minsize=(520, 200),
                         master=master)

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        # top line: a quick summary of the whole table
        self.summary_label = ttk.Label(frame, text=summary_text(table))
        self.summary_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        # the grid: one row per column of the table
        self.grid_view = ttk.Treeview(frame, columns=HEADINGS, show="headings", selectmode="browse")
        for heading, width in zip(HEADINGS, WIDTHS):
            self.grid_view.heading(heading, text=heading)
            numeric = heading in ("Filled", "Empty", "Different", "Smallest", "Largest", "Average")
            # numbers line up on the right, text on the left; only "Most common" soaks up spare width
            self.grid_view.column(heading, width=width, stretch=heading == "Most common",
                                  anchor="e" if numeric else "w")
        for row in profile_rows(table):
            self.grid_view.insert("", "end", values=row)
        self.grid_view.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.grid_view.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.grid_view.configure(yscrollcommand=scroll.set)
