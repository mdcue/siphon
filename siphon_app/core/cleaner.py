"""
siphon_app/core/cleaner.py

Turns text like "$1,234.50", "$2.5B" or "12%" into real numbers, one column at a
time. A column only counts as numeric when most of its cells parse, and a cell that
does not parse is kept as its original text (and counted), never turned into blank.
Nothing here knows about windows or buttons.
"""
import re
from dataclasses import dataclass, field, replace
from decimal import Decimal

from siphon_app.core.models import Cell, Table

NUMERIC_SHARE = 0.8     # a column is numeric if this share of its non-empty cells parse

_CURRENCY = r"(?:[$\u20ac\u00a3\u00a5\u20b9]|Rs\.?)"
_SUFFIX = {"k": 10**3, "m": 10**6, "b": 10**9, "t": 10**12}
_MISSING = {"", "-", "\u2013", "\u2014", "n/a", "na", "n.a.", "none", "null", "?"}
_MINUS = "-\u2212"       # hyphen and the Unicode minus sign
_FOOTNOTE = re.compile(r"\[\s*(?:\d{1,3}|[a-z])\s*\]|[*\u2020\u2021]+$")

# The digits part comes in two styles: "1,234.50" (dot decimal) and "1.234,50" (comma
# decimal). A space also works as a thousands separator.

_BODY = {
    ".": r"(?:\d{1,3}(?:[, ]\d{3})+|\d+)(?:\.\d+)?|\.\d+",
    ",": r"(?:\d{1,3}(?:[. ]\d{3})+|\d+)(?:,\d+)?|,\d+",
}

def _pattern(decimal: str) -> re.Pattern:
    return re.compile(
        rf"^(?:(?P<sign>[{_MINUS}+])\s*)?(?:{_CURRENCY}\s*(?P<sign2>[{_MINUS}+])?\s*)?"
        rf"(?P<body>{_BODY[decimal]})\s*(?P<suffix>[KMBTkmbt](?![A-Za-z]))?\s*"
        rf"(?P<pct>%)?\s*(?:{_CURRENCY})?$"
    )

_PATTERNS = {".": _pattern("."), ",": _pattern(",")}

@dataclass
class Parsed:
    value: int | float
    is_percent: bool = False

def _prepare(text: str) -> str:
    """Strip footnote markers and wrapping spaces: '12[1]' -> '12', '5*' -> '5'."""
    return _FOOTNOTE.sub("", text).strip()

def is_missing(text: str) -> bool:
    """'', '-', 'N/A' and friends: a cell that means 'no value'."""
    return _prepare(text).lower() in _MISSING

def parse_number(text: str, decimal: str = ".") -> Parsed | None:
    """
    Read one cell as a number, or return None if it isn't one.

    decimal is "." for 1,234.50 or "," for 1.234,50.
    Examples: "$1,234.50" -> 1234.5   "$2.5 B" -> 2500000000   "(3.4)" -> -3.4
            "12%" -> 12 (is_percent)   "abc" -> None
    """
    cleaned = _prepare(text)
    negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):    # accounting style negative
        negative, cleaned = True, cleaned[1:-1].strip()
    match = _PATTERNS[decimal].match(cleaned)
    if not match:
        return None
    if any(ch in _MINUS for ch in (match["sign"] or "") + (match["sign2"] or "")):
        negative = True
    body = re.sub(r"[ ,.]", lambda m: "." if m.group() == decimal else "", match["body"])
    number = Decimal(body if not body.startswith(".") else "0" + body)
    if match["suffix"]:
        number *= _SUFFIX[match["suffix"].lower()]
    if negative:
        number = -number
    value: int | float = int(number) if number == number.to_integral_value() else float(number)
    return Parsed(value, is_percent=bool(match["pct"]))

#for whole columns
@dataclass
class ColumnReport:
    name: str # the header, before any "(%)" is added
    converted: int = 0 # cells turned into numbers
    kept_as_text: int = 0 # cells that did not parse and stayed as they were
    is_percent: bool = False
    decimal: str = "."

@dataclass
class CleanReport:
    columns: list[ColumnReport] = field(default_factory=list)   # numeric columns only

    @property
    def cells_converted(self) -> int:
        return sum(c.converted for c in self.columns)

    @property
    def cells_kept_as_text(self) -> int:
        return sum(c.kept_as_text for c in self.columns)

    def summary(self) -> str:
        if not self.columns:
            return "No numeric columns found, so nothing was changed."
        text = f"Converted {len(self.columns)} column(s), {self.cells_converted} cells."
        if self.cells_kept_as_text:
            text += f" {self.cells_kept_as_text} cell(s) didn't look like numbers and were kept as text."
        return text

def _guess_decimal(texts: list[str]) -> str:
    """Pick '.' or ',' for a column by counting cells that only make sense one way."""
    dot = comma = 0
    for text in texts:
        as_dot = _PATTERNS["."].match(_prepare(text).strip("()"))
        as_comma = _PATTERNS[","].match(_prepare(text).strip("()"))
        if as_dot and not as_comma:
            dot += 1
        elif as_comma and not as_dot:
            comma += 1
    return "," if comma > dot else "."

def _has_leading_zero(texts: list[str]) -> bool:
    """'007' or '01234' are codes, not quantities: converting would lose the zeros."""
    return any(re.fullmatch(r"0\d+", _prepare(t)) for t in texts)

def clean_table(table: Table, *, keep_original: bool = False) -> tuple[Table, CleanReport]:
    """Return (cleaned copy, report). The table you pass in is never modified.

    keep_original=True adds the untouched text column next to each converted one,
    named "<header> (original)".
    """
    report = CleanReport()
    headers: list[str] = []
    columns: list[list[Cell]] = []

    for index, header in enumerate(table.headers):
        original = [row[index] for row in table.rows]
        values = [t for t in original if not is_missing(t)]
        decimal = _guess_decimal(values)
        parsed = [parse_number(t, decimal) for t in values]
        good = [p for p in parsed if p is not None]

        numeric = bool(values) and len(good) / len(values) >= NUMERIC_SHARE \
            and not _has_leading_zero(values)
        if not numeric:
            headers.append(header)
            columns.append(list(original))
            continue

        info = ColumnReport(name=header, decimal=decimal)
        is_percent = sum(p.is_percent for p in good) * 2 > len(good) # more than half
        new_column: list[Cell] = []
        for text in original:
            if is_missing(text):
                new_column.append("")
                continue
            result = parse_number(text, decimal)
            if result is None:
                new_column.append(text) # keep it; never blank a cell silently
                info.kept_as_text += 1
            else:
                new_column.append(result.value)
                info.converted += 1
        info.is_percent = is_percent
        report.columns.append(info)

        headers.append(f"{header} (%)" if is_percent and "%" not in header else header)
        columns.append(new_column)
        if keep_original:
            headers.append(f"{header} (original)")
            columns.append(list(original))

    rows = [list(row) for row in zip(*columns)] if columns else []
    warnings = list(table.warnings)
    if report.cells_kept_as_text:
        warnings.append(report.summary())
    return replace(table, headers=headers, rows=rows, warnings=warnings), report

if __name__ == "__main__":
    # Quick terminal check:  python -m siphon_app.core.cleaner tests/fixtures/prices.html
    import sys
    from siphon_app.core.parser import parse_tables

    if len(sys.argv) != 2:
        print("usage: python -m siphon_app.core.cleaner <html file>")
        raise SystemExit(1)
    with open(sys.argv[1], "rb") as handle:
        for found in parse_tables(handle.read()):
            cleaned, rep = clean_table(found)
            print(f"{cleaned.name}: {rep.summary()}")
            print("  ", cleaned.headers)
            for line in cleaned.rows:
                print("  ", line)