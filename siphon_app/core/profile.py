"""
siphon_app/core/profile.py

A quick health check for each column of a table: what kind of data it holds, how
many cells are filled or empty, how many different values it has and, for number
columns, the smallest, largest and average. Nothing here knows about windows.
"""
from collections import Counter
from dataclasses import dataclass

from siphon_app.core.cleaner import NUMERIC_SHARE, is_missing, parse_number
from siphon_app.core.models import Cell, Table

NUMBER, TEXT, EMPTY = "number", "text", "empty"     # the three kinds a column can be

@dataclass
class ColumnProfile:
    name: str
    kind: str                       # NUMBER, TEXT or EMPTY
    filled: int                     # cells that hold something
    empty: int                      # blank cells, "-", "N/A" and friends
    unique: int                     # how many different values the filled cells have
    minimum: float | None = None    # the three below only exist for number columns
    maximum: float | None = None
    mean: float | None = None
    common: str = ""                # the value that shows up most often
    common_count: int = 0           # ...and how many times it does

def _is_empty(cell: Cell) -> bool:
    """A real number (even 0) is never empty. Text is empty if blank or a "no value" marker."""
    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
        return False
    return is_missing(str(cell))

def _as_number(cell: Cell) -> float | None:
    """The cell as a number, or None if it isn't one. Works on "$1,234" text and real numbers."""
    if isinstance(cell, bool):          # True/False are technically ints in Python; not numbers here
        return None
    if isinstance(cell, (int, float)):
        return float(cell)
    parsed = parse_number(str(cell))
    return None if parsed is None else float(parsed.value)

def profile_column(name: str, cells: list[Cell]) -> ColumnProfile:
    filled_cells = [cell for cell in cells if not _is_empty(cell)]
    filled, empty = len(filled_cells), len(cells) - len(filled_cells)
    if not filled_cells:
        return ColumnProfile(name, EMPTY, 0, empty, 0)

    # Same value counted once, whatever the stray spaces around it.
    counts = Counter(str(cell).strip() for cell in filled_cells)
    common, common_count = counts.most_common(1)[0]      # a tie goes to the one seen first
    numbers = [n for n in map(_as_number, filled_cells) if n is not None]

    # Same rule the cleaner uses: 80% numeric or more means "a number column".
    # The stats only look at the cells that really are numbers.
    if len(numbers) / filled >= NUMERIC_SHARE:
        return ColumnProfile(name, NUMBER, filled, empty, len(counts),
                            min(numbers), max(numbers), sum(numbers) / len(numbers),
                            common, common_count)
    return ColumnProfile(name, TEXT, filled, empty, len(counts),
                        common=common, common_count=common_count)

def profile_table(table: Table) -> list[ColumnProfile]:
    """One profile per column, in column order."""
    return [profile_column(header, [row[column] for row in table.rows])
            for column, header in enumerate(table.headers)]