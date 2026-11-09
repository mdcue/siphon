# [NEW FILE] every line is new
"""
siphon_app/core/columns.py

Hiding and renaming columns without touching the original table.

The window keeps the original table safe and asks this file for a reshaped copy.
Previews, Copy and exports all use that copy. Nothing here knows about windows
or buttons, so it is easy to test.
"""
import re
from dataclasses import replace

from siphon_app.core.models import Table


class ColumnError(ValueError):
    """Something we can't do (like hiding every column), worded so we can show it as is."""


def clean_name(text: str) -> str:
    """Tidy a typed name: trim it and squash any run of spaces or line breaks into one space."""
    name = re.sub(r"\s+", " ", text or "").strip()
    if not name:
        raise ColumnError("A column needs a name.")
    return name


def visible_columns(n_cols: int, hidden: set[int]) -> list[int]:
    """The original positions of the columns still showing, in their original order."""
    return [i for i in range(n_cols) if i not in hidden]


def reshape(table: Table, hidden: set[int] | None = None,
            names: dict[int, str] | None = None) -> Table:
    """
    A copy of the table with some columns hidden and some renamed.

    Both `hidden` and `names` use the ORIGINAL column positions, so a rename keeps
    pointing at the right column even after other columns are hidden.
    """
    hidden = hidden or set()
    names = names or {}

    # Fail loudly on a position that doesn't exist: that would be a bug in our code.
    for index in set(hidden) | set(names):
        if not 0 <= index < table.n_cols:
            raise ColumnError(f"Column {index} does not exist in '{table.name}'.")

    keep = visible_columns(table.n_cols, hidden)
    if not keep:
        raise ColumnError("A table needs at least one column.")

    # Nothing to change? Hand back the very same table instead of making a copy.
    if not hidden and not names:
        return table

    headers = [names.get(i, table.headers[i]) for i in keep]
    rows = [[row[i] for i in keep] for row in table.rows]
    # replace() copies every other field (name, source_url, is_layout...); the warnings
    # list is copied by hand so the two tables don't share one list.
    return replace(table, headers=headers, rows=rows, warnings=list(table.warnings))
