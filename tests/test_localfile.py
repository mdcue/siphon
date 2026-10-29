"""Tests for siphon_app/core/localfile.py. Nothing here needs a screen."""
import pytest

from siphon_app.core import localfile
from siphon_app.core.fetcher import FetchedPage, FetchError
from siphon_app.core.localfile import read_html_file
from siphon_app.core.parser import parse_page

PAGE = b"<html><body><h2>Sales</h2><table><tr><th>Name</th><th>Total</th></tr><tr><td>A</td><td>$5</td></tr></table></body></html>"

def test_a_saved_page_is_read_like_a_download(tmp_path):
    path = tmp_path / "page.html"
    path.write_bytes(PAGE)
    page = read_html_file(path)
    assert isinstance(page, FetchedPage)
    assert page.content == PAGE
    assert page.url.startswith("file:///") and page.url.endswith("page.html")
    assert page.content_type == "text/html"

def test_a_saved_page_goes_straight_into_the_parser(tmp_path):
    path = tmp_path / "page.html"
    path.write_bytes(PAGE)
    [table] = parse_page(read_html_file(path))
    assert table.name == "Sales" and table.rows == [["A", "$5"]]
    assert table.source_url.endswith("page.html")

@pytest.mark.parametrize("name", ["a.html", "a.htm", "a.xhtml", "A.HTML", "A.Htm"])
def test_all_the_usual_extensions_work_in_any_case(tmp_path, name):
    (tmp_path / name).write_bytes(PAGE)
    assert read_html_file(tmp_path / name).content == PAGE

def test_a_path_given_as_text_works(tmp_path):
    (tmp_path / "x.html").write_bytes(PAGE)
    assert read_html_file(str(tmp_path / "x.html")).content == PAGE

def test_odd_characters_in_the_file_name_are_fine(tmp_path):
    path = tmp_path / "t\u00e4ble 100% #1 \u8868.html"
    path.write_bytes(PAGE)
    page = read_html_file(path)
    assert page.content == PAGE and "%" in page.url # the address is properly escaped

def test_an_empty_file_is_readable_and_simply_has_no_tables(tmp_path):
    path = tmp_path / "empty.html"
    path.write_bytes(b"")
    assert parse_page(read_html_file(path)) == []

def test_a_missing_file_has_a_friendly_error(tmp_path):
    with pytest.raises(FetchError, match="doesn't exist"):
        read_html_file(tmp_path / "gone.html")

def test_a_folder_is_not_a_page(tmp_path):
    (tmp_path / "pages.html").mkdir() # even a folder with a .html name
    with pytest.raises(FetchError, match="folder"):
        read_html_file(tmp_path / "pages.html")
    with pytest.raises(FetchError, match="folder"):
        read_html_file(tmp_path)

@pytest.mark.parametrize("name, mention", [("data.pdf", ".pdf"), ("notes.txt", ".txt"), ("page", "no extension"),
                                        ("archive.tar.gz", ".gz"), ("picture.PNG", ".png")])
def test_other_kinds_of_file_are_refused_politely(tmp_path, name, mention):
    (tmp_path / name).write_bytes(PAGE)
    with pytest.raises(FetchError, match="saved web pages") as caught:
        read_html_file(tmp_path / name)
    assert mention in str(caught.value)

def test_a_file_over_the_limit_is_refused_before_reading_it(tmp_path, monkeypatch):
    monkeypatch.setattr(localfile, "MAX_BYTES", 100)
    (tmp_path / "big.html").write_bytes(b"x" * 101)
    with pytest.raises(FetchError, match="bigger than"):
        read_html_file(tmp_path / "big.html")

def test_a_file_exactly_at_the_limit_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(localfile, "MAX_BYTES", 100)
    (tmp_path / "ok.html").write_bytes(b"x" * 100)
    assert len(read_html_file(tmp_path / "ok.html").content) == 100

def test_a_file_that_grows_while_being_read_is_still_caught(tmp_path, monkeypatch):
    """The size check passes, but the file is bigger when we actually read it."""
    monkeypatch.setattr(localfile, "MAX_BYTES", 100)
    path = tmp_path / "growing.html"
    path.write_bytes(b"x" * 500)
    real_stat = type(path).stat

    class FakeStat:
        st_mode = real_stat(path).st_mode # still looks like a normal file
        st_size = 10 # but claims to be small

    monkeypatch.setattr(type(path), "stat", lambda self, **kw: FakeStat() if self == path else real_stat(self, **kw))
    with pytest.raises(FetchError, match="bigger than"):
        read_html_file(path)

def test_a_read_problem_becomes_a_friendly_error(tmp_path, monkeypatch):
    path = tmp_path / "locked.html"
    path.write_bytes(PAGE)

    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr("builtins.open", denied)
    with pytest.raises(FetchError, match="protected"):
        read_html_file(path)

    def broken(*args, **kwargs):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr("builtins.open", broken)
    with pytest.raises(FetchError, match="Input/output error"):
        read_html_file(path)