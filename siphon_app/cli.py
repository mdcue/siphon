"""
siphon_app/cli.py

Siphon from the command line, no window:

    python -m siphon_app https://example.com/prices -f xlsx -o C:\\Users\\me\\Downloads
    python -m siphon_app saved_page.html --list

It uses the same core as the window (polite fetching, parser, cleaner, exporter), so a
file saved here is the same as one saved from the app. Nothing in here imports tkinter.
"""
import argparse
import sys
from pathlib import Path

from siphon_app import __version__
from siphon_app.core.fetcher import FetchError, normalize_url
from siphon_app.core.localfile import HTML_EXTENSIONS, read_html_file
from siphon_app.core.exporter import ExportError
from siphon_app.core.models import Table
from siphon_app.core.parser import parse_page
from siphon_app.core.pipeline import FORMATS, clean_all, describe, export_tables, summarize
from siphon_app.core.polite import polite_fetch

# exit codes: 0 worked, 1 something went wrong (bad page, nothing found, can't save), 2 bad command
OK, FAILED, USAGE = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="siphon",
        description="Pull the tables off a web page and save them as CSV, Excel or JSON.",
        epilog="Run with no arguments to open the window instead.")
    parser.add_argument("source", help="a web address, or a web page you saved (.html / .htm)")
    parser.add_argument("-f", "--format", choices=list(FORMATS), default="csv",
                        help="what to save as (default: csv)")
    parser.add_argument("-o", "--out", default=".", metavar="FOLDER",
                        help="folder to save into (default: the current folder)")
    parser.add_argument("-t", "--table", action="append", metavar="N",
                        help="only this table, by the number --list shows. Repeat it, or use 1,3,4")
    parser.add_argument("-a", "--all", action="store_true",
                        help="include tables that look like page layout (they're skipped by default)")
    parser.add_argument("-l", "--list", action="store_true", help="show the tables found and stop")
    parser.add_argument("--raw", action="store_true", help="keep every cell as text, don't turn numbers into numbers")
    parser.add_argument("-q", "--quiet", action="store_true", help="only print the saved file names")
    parser.add_argument("--version", action="version", version=f"siphon {__version__}")
    return parser


def looks_like_file(source: str) -> bool:
    """A saved page, not an address: it has no '://' and it exists on this computer (or ends in .html)."""
    if "://" in source:
        return False
    return Path(source).suffix.lower() in HTML_EXTENSIONS or Path(source).exists()


def parse_numbers(values: list[str] | None, count: int) -> list[int]:
    """'-t 1 -t 3,4' -> [0, 2, 3] (positions). Raises ValueError with a message that is safe to show."""
    picked: list[int] = []
    for value in values or []:
        for piece in value.split(","):
            piece = piece.strip()
            if not piece:
                continue
            if not piece.isdigit():
                raise ValueError(f"'{piece}' isn't a table number.")
            number = int(piece)
            if not 1 <= number <= count:
                raise ValueError(f"There's no table {number}. This page has {count}.")
            if number - 1 not in picked:
                picked.append(number - 1)
    return picked


def table_line(number: int, table: Table) -> str:
    """'2. Prices - 10 rows x 4 columns (looks like page layout)'"""
    line = f"{number}. {table.name} - {table.n_rows:,} rows x {table.n_cols} columns"
    return line + " (looks like page layout)" if table.is_layout else line


def run(argv: list[str], out=None, err=None, fetch=polite_fetch) -> int:
    """Do one job and return the exit code. out/err/fetch can be swapped, which is how the tests run it."""
    out = out or sys.stdout
    err = err or sys.stderr

    def say(text: str) -> None:
        print(text, file=err)

    def fail(text: str, code: int = FAILED) -> int:
        say(f"siphon: {text}")
        return code

    try:
        args = build_parser().parse_args(argv)
    except SystemExit as stop:                    # --help, --version and bad commands all end up here
        return int(stop.code or 0)

    # get the page
    try:
        if looks_like_file(args.source):
            page = read_html_file(args.source)
        else:
            url = normalize_url(args.source)
            if not args.quiet:
                say(f"Downloading {url} ...")
            page = fetch(url)
    except FetchError as error:
        return fail(str(error))
    if page.note and not args.quiet:
        say(page.note)

    tables = parse_page(page)
    if not tables:
        return fail("No tables found on that page. If it builds its tables with JavaScript, "
                    "save it from your browser and open the saved file instead.")

    if args.list:
        for number, table in enumerate(tables, start=1):
            print(table_line(number, table), file=out)
        return OK

    # pick the tables
    try:
        picked = parse_numbers(args.table, len(tables))
    except ValueError as error:
        return fail(str(error), USAGE)
    if picked:
        chosen = [tables[i] for i in picked]
    else:
        chosen = [t for t in tables if args.all or not t.is_layout]
        if not chosen:
            return fail(f"All {len(tables)} tables look like page layout. "
                        "Use --all to save them anyway, or pick one with -t.")

    # clean and save
    reports = []
    if not args.raw:
        cleaned = clean_all(chosen)
        chosen = [table for table, _ in cleaned]
        reports = [report for _, report in cleaned]
    try:
        paths = export_tables(chosen, args.format, args.out)
    except ExportError as error:
        return fail(str(error))
    if reports and not args.quiet:
        say(summarize(reports))
    if not args.quiet:
        say(describe(paths))
    for path in paths:
        print(path, file=out)                     # the file names go to stdout, so other programs can read them
    return OK


def opened_by_double_click() -> bool:
    """True on Windows when this program has a console all to itself, which is what a double-click gives it.
    From cmd there are two programs sharing the console (cmd and us)."""
    if sys.platform != "win32":
        return False
    import ctypes
    room = (ctypes.c_uint * 4)()
    return ctypes.windll.kernel32.GetConsoleProcessList(room, 4) <= 1


def main() -> None:
    """Entry point used by __main__: run, then exit with the result."""
    for stream in (sys.stdout, sys.stderr):       # a Windows console can't print every character; don't crash on one
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    if len(sys.argv) == 1:                        # nothing to do: show how to use it
        build_parser().print_help()
        if opened_by_double_click():              # a double-clicked console closes at once, so hold it open
            input("\nPress Enter to close this window.")
        sys.exit(USAGE)
    try:
        code = run(sys.argv[1:])
    except KeyboardInterrupt:
        print("siphon: stopped.", file=sys.stderr)
        code = 130
    sys.exit(code)
