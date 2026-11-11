"""
siphon_app/core/models.py

The one data structure the whole app passes around: a Table.
"""
from dataclasses import dataclass, field

# A cell is text straight from the page, or a number once the cleaner has converted it.
Cell = str | int | float

@dataclass
class Table:
    """One scraped table: a name, column headers and rows of cells."""
    name: str                       # guessed from caption / nearest heading
    headers: list[str]              # column names
    rows: list[list[Cell]]          # every row has exactly len(headers) cells
    source_url: str = ""            # where the table came from
    warnings: list[str] = field(default_factory=list)  # e.g. "1 merged row repaired"
    is_layout: bool = False         # the parser's guess: probably page layout, not data

    def __post_init__(self) -> None:
        # Every row must be as wide as the headers. A ragged table means a parser bug,
        # so fail here instead of corrupting an export later.
        width = len(self.headers)
        for i, row in enumerate(self.rows, start=1):
            if len(row) != width:
                raise ValueError(
                    f"Row {i} of table '{self.name}' has {len(row)} cells, "
                    f"expected {width}."
                )

    @property
    def n_rows(self) -> int:
        """How many data rows (the header is not counted)."""
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        """How many columns."""
        return len(self.headers)