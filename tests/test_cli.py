"""Tests for siphon_app/cli.py (the command-line mode). Nothing here needs a screen or the internet."""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from siphon_app import cli
from siphon_app.cli import FAILED, OK, USAGE, looks_like_file, parse_numbers, run, table_line
from siphon_app.core.fetcher import FetchedPage, FetchError
from siphon_app.core.models import Table

PRICES = """<table><caption>Prices</caption>
<tr><th>Name</th><th>Price</th></tr>
<tr><td>Alpha</td><td>$1,234</td></tr><tr><td>Beta</td><td>$5</td></tr></table>"""
STOCK = """<table><caption>Stock</caption>
<tr><th>Item</th><th>Count</th></tr>
<tr><td>Nut</td><td>10</td></tr><tr><td>Bolt</td><td>20</td></tr></table>"""
LAYOUT = "<table><tr><td>just a banner</td></tr></table>"


@pytest.fixture
def page_file(tmp_path):
    """Make a saved web page in a temp folder and return its path."""
    def make(*tables):
        path = tmp_path / "page.html"
        path.write_text("<html><body>" + "".join(tables) + "</body></html>", encoding="utf-8")
        return str(path)
    return make


def go(*argv, fetch=None):
    """Run the CLI and hand back (exit code, stdout text, stderr text)."""
    out, err = io.StringIO(), io.StringIO()
    kwargs = {"fetch": fetch} if fetch else {}
    code = run(list(argv), out=out, err=err, **kwargs)
    return code, out.getvalue(), err.getvalue()


# -- small helpers

def test_parse_numbers_turns_table_numbers_into_positions():
    assert parse_numbers(["1", "3,4"], 5) == [0, 2, 3]
    assert parse_numbers(["2", "2"], 5) == [1]                    # no doubles
    assert parse_numbers(None, 5) == []


@pytest.mark.parametrize("bad", ["0", "6", "x", "-1", "1.5"])
def test_parse_numbers_rejects_bad_numbers(bad):
    with pytest.raises(ValueError):
        parse_numbers([bad], 5)


def test_looks_like_file(tmp_path):
    assert looks_like_file("page.html")
    assert looks_like_file("PAGE.HTM")
    assert not looks_like_file("https://example.com/page.html")
    assert not looks_like_file("example.com")
    other = tmp_path / "notes.txt"
    other.write_text("hi")
    assert looks_like_file(str(other))                            # exists, so it gets a proper "not a web page" message


def test_table_line_says_when_a_table_looks_like_layout():
    table = Table("Prices", ["A", "B"], [["1", "2"]])
    assert table_line(2, table) == "2. Prices - 1 rows x 2 columns"
    table.is_layout = True
    assert table_line(2, table).endswith("(looks like page layout)")


# -- listing

def test_list_shows_every_table_and_saves_nothing(page_file, tmp_path):
    code, out, _ = go(page_file(PRICES, LAYOUT, STOCK), "--list", "-o", str(tmp_path / "out"))
    assert code == OK
    lines = out.strip().splitlines()
    assert lines[0].startswith("1. Prices")
    assert "looks like page layout" in lines[1]
    assert lines[2].startswith("3. Stock")
    assert not (tmp_path / "out").exists()


# -- saving

def test_csv_is_the_default_and_the_saved_path_goes_to_stdout(page_file, tmp_path):
    code, out, err = go(page_file(PRICES), "-o", str(tmp_path))
    assert code == OK
    saved = Path(out.strip())
    assert saved.name == "Prices.csv" and saved.exists()
    assert saved.read_text(encoding="utf-8-sig").splitlines()[1] == "Alpha,1234"     # cleaned into a number
    assert "Saved Prices.csv" in err                                                # the chatty part is on stderr


def test_json_and_xlsx_formats(page_file, tmp_path):
    code, out, _ = go(page_file(PRICES), "-f", "json", "-o", str(tmp_path))
    assert code == OK and json.loads(Path(out.strip()).read_text(encoding="utf-8"))
    code, out, _ = go(page_file(PRICES), "-f", "xlsx", "-o", str(tmp_path))
    assert code == OK and Path(out.strip()).suffix == ".xlsx"


def test_raw_keeps_the_text_as_it_was(page_file, tmp_path):
    code, out, _ = go(page_file(PRICES), "--raw", "-o", str(tmp_path))
    assert "$1,234" in Path(out.strip()).read_text(encoding="utf-8-sig")


def test_layout_tables_are_skipped_unless_asked_for(page_file, tmp_path):
    source = page_file(PRICES, LAYOUT)
    _, out, _ = go(source, "-o", str(tmp_path / "a"))
    assert len(out.strip().splitlines()) == 1
    _, out, _ = go(source, "--all", "-o", str(tmp_path / "b"))
    assert len(out.strip().splitlines()) == 2


def test_only_layout_tables_gives_a_helpful_error(page_file, tmp_path):
    code, out, err = go(page_file(LAYOUT), "-o", str(tmp_path))
    assert code == FAILED and out == ""
    assert "--all" in err


def test_picking_tables_by_number(page_file, tmp_path):
    code, out, _ = go(page_file(PRICES, STOCK), "-t", "2", "-o", str(tmp_path))
    assert code == OK
    assert [Path(p).name for p in out.splitlines()] == ["Stock.csv"]


def test_a_picked_layout_table_is_saved_even_without_all(page_file, tmp_path):
    code, out, _ = go(page_file(PRICES, LAYOUT), "-t", "2", "-o", str(tmp_path))
    assert code == OK and len(out.splitlines()) == 1


def test_a_bad_table_number_is_a_usage_error(page_file, tmp_path):
    code, out, err = go(page_file(PRICES), "-t", "5", "-o", str(tmp_path))
    assert code == USAGE and out == ""
    assert "no table 5" in err
    assert list(tmp_path.glob("*.csv")) == []


def test_running_twice_never_overwrites(page_file, tmp_path):
    source = page_file(PRICES)
    go(source, "-o", str(tmp_path))
    _, out, _ = go(source, "-o", str(tmp_path))
    assert Path(out.strip()).name != "Prices.csv"
    assert len(list(tmp_path.glob("*.csv"))) == 2


def test_quiet_prints_only_the_file_names(page_file, tmp_path):
    code, out, err = go(page_file(PRICES), "-q", "-o", str(tmp_path))
    assert code == OK and err == "" and out.strip().endswith("Prices.csv")


# -- things going wrong

def test_a_page_without_tables_is_an_error(page_file):
    code, out, err = go(page_file("<p>nothing here</p>"))
    assert code == FAILED and "No tables found" in err and out == ""


def test_a_missing_file_is_an_error():
    code, _, err = go("definitely-not-here.html")
    assert code == FAILED and "doesn't exist" in err


def test_a_folder_that_cant_be_used_is_an_error(page_file, tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("hi")
    code, out, err = go(page_file(PRICES), "-o", str(blocker))
    assert code == FAILED and out == "" and err.startswith("siphon: ")


def test_no_source_or_a_wrong_option_is_a_usage_error():
    assert go()[0] == USAGE
    assert go("page.html", "-f", "pdf")[0] == USAGE


def test_help_and_version_exit_cleanly(capsys):
    assert go("--version")[0] == OK
    assert go("--help")[0] == OK


# -- addresses (the download is swapped for a fake one)

def test_an_address_is_tidied_and_downloaded():
    asked = []

    def fake_fetch(url):
        asked.append(url)
        return FetchedPage(url=url, content=PRICES.encode(), content_type="text/html", note="Used the copy from 5 seconds ago.")

    code, out, err = go("example.com/prices", "--list", fetch=fake_fetch)
    assert code == OK
    assert asked == ["https://example.com/prices"]
    assert out.startswith("1. Prices")
    assert "Used the copy" in err


def test_a_download_problem_is_shown_without_a_traceback():
    def broken(url):
        raise FetchError("example.com refused the connection.")

    code, out, err = go("https://example.com", fetch=broken)
    assert code == FAILED and out == ""
    assert err.strip().endswith("siphon: example.com refused the connection.")


def test_a_bad_address_is_reported():
    code, _, err = go("mailto:me@x.com")
    assert code == FAILED and "http" in err


# -- the real thing, start to finish

def test_python_dash_m_runs_the_command_line_without_tkinter(page_file, tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "siphon_app", page_file(PRICES), "-q", "-o", str(tmp_path)],
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).name == "Prices.csv"


# -- started with nothing to do (a double-click on siphon-cli.exe)

def test_main_with_no_arguments_shows_the_help_and_exits_with_a_usage_code(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["siphon"])
    monkeypatch.setattr(cli, "opened_by_double_click", lambda: False)
    with pytest.raises(SystemExit) as stop:
        cli.main()
    assert stop.value.code == USAGE
    assert "usage: siphon" in capsys.readouterr().out


def test_a_double_clicked_console_waits_before_closing(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["siphon"])
    monkeypatch.setattr(cli, "opened_by_double_click", lambda: True)
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or "")
    with pytest.raises(SystemExit):
        cli.main()
    assert len(asked) == 1


def test_a_double_click_is_only_ever_detected_on_windows():
    if sys.platform != "win32":
        assert cli.opened_by_double_click() is False
