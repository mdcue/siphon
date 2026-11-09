"""
siphon_app/core/parser.py

Turns a page's HTML into a list of Table objects.

What it takes care of:
  * a table only reads its OWN rows (a table nested inside it is a separate table)
  * merged cells (colspan / rowspan) are spread out into a neat rectangular grid
  * header rows are found and joined into one name per column
  * each table gets a readable name (caption, nearest heading, ...)
  * tables that look like page layout are flagged, never silently thrown away
Nothing here knows about windows or buttons.
"""
import codecs
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from siphon_app.core.models import Table

if TYPE_CHECKING:                       # only for type hints, so nothing is imported at run time
    from siphon_app.core.fetcher import FetchedPage

# lxml handles tables that leave out closing </td> or </tr> tags (legal HTML, common
# on older sites). Python's built-in "html.parser" nests those cells inside each
# other and glues their text together.
PARSER = "lxml"

BIG_SPAN = 30            # a colspan above this means "the whole row" (sites write 99, 1000...)
MAX_COLUMNS = 200        # safety limit so a nasty page can't make a giant grid
MAX_NAME_LENGTH = 100    # longer table names get cut with "..."

DROP_TAGS = ["script", "style", "noscript", "template"]    # thrown away along with everything inside them
HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]
# Pad these with spaces so text around them doesn't get glued together ("Hello<p>World" -> "Hello World").
BLOCK_TAGS = ["p", "div", "li", "ul", "ol", "dl", "dt", "dd", "blockquote", "pre",
              "section", "article", "address"] + HEADING_TAGS

_NUMERIC = re.compile(r"[\s$\u20ac\u00a3\u00a5\u20b9+\-\u2212(]*\d[\d,.\s]*[%)KMBTkmbt]*")     # "12", "$1,234.50", "3.4%", "(5)", plus euro/pound/yen/rupee signs and the Unicode minus
_FOOTNOTE = re.compile(r"(?:\s*\[(?:\d{1,3}|[a-z]|note \d{1,3})\])+$")  # "Population[1]", "Rank [a]"
_EDIT_MARK = re.compile(r"\s*\[(?:edit|\d{1,3})\]$", re.IGNORECASE)    # Wikipedia headings: "History[edit]"


# ---- small containers used while reading ------------------------------------

@dataclass
class _Cell:                  # one <td>/<th> as written in the HTML
    text: str
    is_th: bool
    colspan: int
    rowspan: int              # 0 means "all the way down", same as HTML


@dataclass
class _Row:                   # one <tr>
    cells: list[_Cell]
    in_thead: bool


@dataclass
class _Slot:                  # one square of the finished grid
    text: str
    is_th: bool
    copied: bool = False      # True when this square is just a copy from a merged cell


# ---- public functions ------------------------------------------------------------

def parse_tables(markup: bytes | str, source_url: str = "", encoding: str | None = None) -> list[Table]:
    """Find every <table> in the page and return the ones that have something in them.

    markup:   the page, as raw bytes (best) or text
    encoding: a charset to try first, e.g. the one from the HTTP header
    """
    options = {"from_encoding": encoding} if encoding and isinstance(markup, bytes) else {}
    soup = BeautifulSoup(markup, PARSER, **options)
    _prepare(soup)

    tables = []
    for tag in soup.find_all("table"):          # page order, so a nested table comes after its parent
        table = _parse_table(tag, source_url)
        if table is not None:
            tables.append(table)

    # Give nameless tables "Table 1", "Table 2"... then make every name unique.
    for number, table in enumerate(tables, start=1):
        if not table.name:
            table.name = f"Table {number}"
    for table, name in zip(tables, _unique_names([t.name for t in tables])):
        table.name = name
    return tables


def parse_page(page: "FetchedPage") -> list[Table]:
    """Shortcut: parse what fetch() gave back, using its URL and charset."""
    return parse_tables(
        page.content,
        source_url=page.url,
        encoding=charset_from_content_type(page.content_type),
    )


def charset_from_content_type(content_type: str) -> str | None:
    """'text/html; charset=utf-8' -> 'utf-8'. None if missing or not a charset Python knows."""
    match = re.search(r"charset\s*=\s*[\"']?([A-Za-z0-9_.:\-]+)", content_type or "", re.IGNORECASE)
    if not match:
        return None
    try:
        codecs.lookup(match.group(1))
    except LookupError:
        return None
    return match.group(1)


# ---- reading the HTML -------------------------------------------------------

def _prepare(soup: BeautifulSoup) -> None:
    """Tidy the whole page once, before any table is read.

    It's a single scan on purpose: every scan of a big page costs real time.
    """
    for tag in soup.find_all(DROP_TAGS + ["br"] + BLOCK_TAGS):
        if tag.decomposed:                      # it was inside something we already removed
            continue
        if tag.name in DROP_TAGS:
            tag.decompose()                     # their text is code or notices, not table content
        elif tag.name == "br":
            tag.replace_with(" ")
        else:
            tag.insert_before(" ")
            tag.insert_after(" ")


def _cell_text(tag) -> str:
    """The visible text of a tag, with whitespace squashed down to single spaces."""
    text = tag.get_text("").replace("\u200b", "")      # zero-width spaces are invisible junk
    return re.sub(r"\s+", " ", text).strip()           # \s also catches non-breaking spaces


def _span(cell, attribute: str) -> int:
    """Read a colspan/rowspan number, or 1 if it's missing or nonsense."""
    match = re.match(r"\s*(\d+)", str(cell.get(attribute, "")))   # browsers accept "2px" as 2
    return int(match.group(1)) if match else 1


def _locate(tr) -> tuple:
    """Walk up from a <tr> to find (its table, the thead/tbody/tfoot around it or None).

    Walking up by hand is much faster than find_parent, which matters on
    tables with tens of thousands of rows.
    """
    section = None
    for parent in tr.parents:
        if parent.name == "table":
            return parent, section
        if section is None and parent.name in ("thead", "tbody", "tfoot"):
            section = parent.name
    return None, section


def _read_rows(table_tag) -> list[_Row]:
    """Read this table's own rows into _Row objects (cells not yet spread out)."""
    rows = []
    for tr in table_tag.find_all("tr"):                # this also finds rows of nested tables...
        owner, section = _locate(tr)
        if owner is not table_tag:
            continue                                   # ...so skip them: a nested table is read on its own
        cells = [
            _Cell(
                text=_cell_text(cell),
                is_th=cell.name == "th",
                colspan=max(1, _span(cell, "colspan")),
                rowspan=_span(cell, "rowspan"),
            )
            for cell in tr.children                    # direct children only; stray text has no .name
            if getattr(cell, "name", None) in ("td", "th")
        ]
        rows.append(_Row(cells=cells, in_thead=section == "thead"))
    return rows


# ---- merged cells -> rectangular grid ---------------------------------------

def _natural_width(rows: list[_Row]) -> int:
    """How wide the table really is, ignoring 'whole row' colspans like colspan="1000"."""
    width = 1
    for row in rows:
        width = max(width, sum(c.colspan for c in row.cells if c.colspan <= BIG_SPAN))
    return width


def _use_carry(carry: dict, column: int) -> _Slot:
    """Use one row of a cell that reaches down from an earlier row (rowspan)."""
    remaining, slot = carry[column]
    if remaining <= 1:
        del carry[column]
    else:
        carry[column][0] = remaining - 1
    return _Slot(slot.text, slot.is_th, copied=True)


def _expand(rows: list[_Row]) -> tuple[list[list[_Slot]], bool]:
    """Place every cell on a grid, copying a merged cell into every square it covers.

    Returns (grid, truncated). carry remembers cells still reaching down into
    later rows: {column: [rows left, slot]}. truncated is True if we hit MAX_COLUMNS.
    """
    natural = _natural_width(rows)
    grid: list[list[_Slot]] = []
    carry: dict[int, list] = {}
    truncated = False

    for index, row in enumerate(rows):
        rows_left = len(rows) - index
        out: list[_Slot] = []
        column = 0
        position = 0                                   # next cell of this row still to place

        while position < len(row.cells) or any(c >= column for c in carry):
            if column >= MAX_COLUMNS:
                truncated = True
                break
            if column in carry:                        # a rowspan cell from above sits here
                out.append(_use_carry(carry, column))
                column += 1
                continue
            if position >= len(row.cells):             # row ran out before a carried cell: fill the gap
                out.append(_Slot("", False))
                column += 1
                continue

            cell = row.cells[position]
            position += 1
            span = cell.colspan
            if span > BIG_SPAN:                        # "whole row" marker: stretch to the table width
                span = max(natural - column, 1)
            down = rows_left if cell.rowspan == 0 else min(cell.rowspan, rows_left)

            for k in range(span):
                if column >= MAX_COLUMNS:
                    truncated = True
                    break
                if column in carry:                    # broken HTML: two merged cells overlap
                    _use_carry(carry, column)          # newer cell wins, older one just loses a row
                slot = _Slot(cell.text, cell.is_th, copied=k > 0)
                out.append(slot)
                if down > 1:
                    carry[column] = [down - 1, slot]
                column += 1
        grid.append(out)
    return grid, truncated


# ---- headers ----------------------------------------------------------------

def _looks_like_header(row: list[_Slot]) -> bool:
    """For tables with no <th>/<thead>: does the first row look like column names?"""
    texts = [slot.text for slot in row]
    filled = [t for t in texts if t]
    if len(filled) < max(1, len(texts) / 2):
        return False                                   # mostly empty cells
    return not any(_NUMERIC.fullmatch(t) for t in filled)   # numbers mean data, not names


def _count_header_rows(in_thead: list[bool], grid: list[list[_Slot]]) -> int:
    """How many rows at the top are headers: <thead> first, then all-<th> rows, then a guess."""
    total = len(grid)
    count = 0
    while count < total and in_thead[count]:           # 1) rows the page marks as <thead>
        count += 1
    if count:
        return count
    while count < total and all(slot.is_th for slot in grid[count]):   # 2) leading rows made only of <th>
        count += 1
    if count == total and total > 1:
        count = 1                                      # all-<th> table: keep the rest as data
    if count:
        return count
    return 1 if _looks_like_header(grid[0]) else 0     # 3) guess from the first row's content


def _header_names(header_rows: list[list[_Slot]], width: int) -> list[str]:
    """One name per column; stacked header rows are joined, e.g. 'Population' + '2020'."""
    names = []
    for column in range(width):
        parts: list[str] = []
        for row in header_rows:
            text = _FOOTNOTE.sub("", row[column].text).strip()
            if text and (not parts or parts[-1] != text):   # skip repeats a rowspan creates
                parts.append(text)
        names.append(" ".join(parts))
    return names


def _unique_names(names: list[str]) -> list[str]:
    """Make names unique: 'Name', 'Name' -> 'Name', 'Name (2)'."""
    seen: set[str] = set()
    result = []
    for name in names:
        candidate = name
        number = 2
        while candidate in seen:
            candidate = f"{name} ({number})"
            number += 1
        seen.add(candidate)
        result.append(candidate)
    return result


# ---- naming -----------------------------------------------------------------

def _clean_name(text: str) -> str:
    """Squash spaces, drop Wikipedia's [edit] marks and cut very long names short."""
    text = _EDIT_MARK.sub("", re.sub(r"\s+", " ", text).strip())
    if len(text) > MAX_NAME_LENGTH:
        text = text[: MAX_NAME_LENGTH - 3].rstrip() + "..."
    return text


def _guess_name(tag) -> str:
    """Name a table: its caption, else the nearest heading above, else an attribute, else ''."""
    caption = tag.find("caption", recursive=False)
    if caption is not None and (name := _clean_name(_cell_text(caption))):
        return name
    heading = tag.find_previous(HEADING_TAGS)
    if heading is not None and (name := _clean_name(_cell_text(heading))):
        return name
    for attribute in ("aria-label", "summary", "title"):
        if name := _clean_name(str(tag.get(attribute, ""))):
            return name
    identifier = str(tag.get("id", ""))
    if re.fullmatch(r"[A-Za-z][A-Za-z_\- ]{2,}", identifier):    # "population-table" yes, "ctl00_x7" no
        return _clean_name(re.sub(r"[_\-]+", " ", identifier))
    return ""


# ---- one table --------------------------------------------------------------

def _plural(count: int, noun: str) -> str:
    """'1 row' or '3 rows'."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _parse_table(tag, source_url: str) -> Table | None:
    """Turn one <table> into a Table, or None if there's nothing worth keeping."""
    rows = _read_rows(tag)
    if not rows:
        return None
    grid, truncated = _expand(rows)
    in_thead = [row.in_thead for row in rows]

    # Rows with no text at all are just spacers. Drop them (and their thead flags).
    keep = [i for i, row in enumerate(grid) if any(slot.text for slot in row)]
    if not keep:
        return None
    grid = [grid[i] for i in keep]
    in_thead = [in_thead[i] for i in keep]

    header_count = _count_header_rows(in_thead, grid)
    width = max(len(row) for row in grid)
    header_rows, body = grid[:header_count], grid[header_count:]

    short_rows = sum(1 for row in body if len(row) < width)
    for row in grid:
        row.extend(_Slot("", False) for _ in range(width - len(row)))   # pad short rows so nothing gets dropped
    merged_rows = sum(1 for row in body if any(slot.copied for slot in row))

    warnings: list[str] = []
    if header_count:
        raw_names = _header_names(header_rows, width)
    else:
        raw_names = [""] * width
        warnings.append("No header row found, so the columns are numbered.")

    # An unnamed, empty column is just page spacing.
    columns = [i for i in range(width) if raw_names[i] or any(row[i].text for row in body)]
    if not columns:
        return None
    if len(columns) < width:
        warnings.append(f"Removed {_plural(width - len(columns), 'empty column')}.")

    headers = _unique_names([raw_names[i] or f"Column {i + 1}" for i in columns])
    data = [[row[i].text for i in columns] for row in body]

    if merged_rows:
        warnings.append(
            f"{_plural(merged_rows, 'row')} had merged cells; the text was copied into "
            "every column or row the merged cell covers."
        )
    if short_rows:
        warnings.append(f"{_plural(short_rows, 'row')} had fewer cells than the others and was filled in with empty cells.")
    if truncated:
        warnings.append(f"Only the first {MAX_COLUMNS} columns were read.")

    is_layout = False
    if tag.find("table") is not None:
        is_layout = True
        warnings.append("Contains another table inside it, so it is probably page layout.")
    elif len(headers) < 2 or len(data) < 2:
        is_layout = True
        warnings.append("Fewer than 2 rows or 2 columns, so it may be page layout.")

    return Table(
        name=_guess_name(tag),
        headers=headers,
        rows=data,
        source_url=source_url,
        warnings=warnings,
        is_layout=is_layout,
    )


if __name__ == "__main__":
    # Quick check from the terminal, no window needed:
    #   python -m siphon_app.core.parser tests/fixtures/prices.html
    #   python -m siphon_app.core.parser https://example.com/page-with-tables
    import sys
    from pathlib import Path

    from siphon_app.core.fetcher import FetchError, fetch

    sys.stdout.reconfigure(errors="replace")          # don't crash on characters the console can't show
    for source in sys.argv[1:]:
        print(f"== {source}")
        try:
            if Path(source).is_file():
                found = parse_tables(Path(source).read_bytes(), source_url=source)
            else:
                found = parse_page(fetch(source))
        except FetchError as error:
            print("ERROR", error)
            continue
        if not found:
            print("   no tables found")
        for number, table in enumerate(found, start=1):
            flag = "  [probably layout]" if table.is_layout else ""
            print(f"{number}. {table.name}  ({table.n_rows} rows x {table.n_cols} columns){flag}")
            print("   columns:", " | ".join(table.headers))
            for row in table.rows[:3]:
                print("   row:    ", " | ".join(cell[:25] for cell in row))
            for warning in table.warnings:
                print("   note:   ", warning)
