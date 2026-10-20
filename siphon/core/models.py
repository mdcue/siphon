"""
siphon/core/models.py

The one data structure the whole app passes around: a Table.
"""
from dataclasses import dataclass, field

@dataclass
class Table:
    name: str
    headers: list[str]  #column names
    rows: list[list[str]] #every row will have exactly len(headers) cells
    source_url: str = "" #the source of the table
    warnings: list[str] = field(default_factory = list)
    is_layout: bool = False #this is the parser's guess, probably page layout, not data
    
    def __post_init__(self) -> None:
        #Fail fast: a ragged table means a parser bug, so stop right here
        #instead of letting it corrupt an export later
        width = len(self.headers)
        for i, row in enumerate(self.rows, start = 1):
            if len(row) != width:
                raise ValueError(
                    f"Row {i} of table '{self.name}' has {len(row)} cells, "
                    f"expected {width}."
                )
    
    @property
    def n_rows(self) -> int:
        return len(self.rows)
    
    @property
    def n_cols(self) -> int:
        return len(self.headers)