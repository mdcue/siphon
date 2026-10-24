"""Smoke tests for the main window. They are skipped on a machine with no screen."""
import threading
import time

import pytest

tk = pytest.importorskip("tkinter")

from siphon_app.core.fetcher import FetchCancelled, FetchedPage, FetchError
from siphon_app.core.models import Table
from siphon_app.gui import app as app_module
from siphon_app.gui.app import LIGHT_THEME, READY_TEXT, SiphonApp

@pytest.fixture(scope="module")
def app():
    try:
        window = SiphonApp()
    except tk.TclError:
        pytest.skip("no display available")
    window.withdraw() # don't flash a window during the tests
    yield window
    window.destroy()

#helpers
PAGE = FetchedPage(url="https://example.com/data", content=b"<html></html>", content_type="text/html")

def wait_until_idle(app, timeout=5.0):
    """Let the window process events until the background job has been handled."""
    end = time.time() + timeout
    while app.busy and time.time() < end:
        app.update()
        time.sleep(0.01)
    app.update()
    assert not app.busy, "the window never finished the job"

def run_fetch(app, monkeypatch, url="example.com/data", *, fetch=None, parse=None):
    """Put a url in the box, swap in fake fetch/parse functions, and press Fetch."""
    monkeypatch.setattr(app_module, "fetch", fetch or (lambda u, cancel_event=None: PAGE))
    monkeypatch.setattr(app_module, "parse_page", parse or (lambda page: []))
    app.url_var.set(url)
    app.on_fetch()

#the window
def test_window_starts_ready_with_the_light_theme(app):
    assert app.title() == "siphon."
    assert app.status_var.get() == READY_TEXT
    assert app.style.theme.name == LIGHT_THEME
    assert app.style.theme_mode == "light"
    assert not app.status_is_error
    assert not app.busy and str(app.cancel_button.cget("state")) == "disabled"

def test_a_bad_address_shows_the_reason_in_the_status_bar(app):
    app.url_var.set("mailto:someone@example.com")
    app.on_fetch()
    assert "http and https" in app.status_var.get()
    assert app.status_is_error
    assert not app.busy

def test_an_empty_address_is_rejected(app):
    app.url_var.set("   ")
    app.on_fetch()
    assert app.status_var.get() != READY_TEXT
    assert app.status_is_error
    assert not app.busy

def test_theme_button_switches_to_dark_and_back(app):
    app.toggle_theme()
    assert app.style.theme_mode == "dark"
    assert app.theme_button.cget("text") == "Light" # the button now offers the other theme
    app.toggle_theme()
    assert app.style.theme_mode == "light"
    assert app.theme_button.cget("text") == "Dark"

def test_enter_in_the_url_box_fetches(app):
    assert app.url_entry.bind("<Return>") # a handler is attached

#downloading in background
def test_a_good_address_is_tidied_and_downloaded(app, monkeypatch):
    seen = []
    def fake_fetch(url, cancel_event=None):
        seen.append(url)
        return PAGE
    tables = [Table("Prices", ["A", "B"], [["1", "2"], ["3", "4"]])]
    run_fetch(app, monkeypatch, "  example.com/data ", fetch=fake_fetch, parse=lambda page: tables)
    wait_until_idle(app)
    assert app.url_var.get() == "https://example.com/data" # https:// added, spaces gone
    assert seen == ["https://example.com/data"]
    assert app.tables == tables
    assert app.status_var.get() == "Found 1 table."
    assert not app.status_is_error
    assert "Prices" in app.content_label.cget("text") and "2 rows" in app.content_label.cget("text")

def test_several_tables_and_layout_tables_are_described(app, monkeypatch):
    tables = [Table("Sales", ["A", "B"], [["1", "2"]]),
            Table("Menu", ["A"], [["x"]], is_layout=True)]
    run_fetch(app, monkeypatch, parse=lambda page: tables)
    wait_until_idle(app)
    assert app.status_var.get() == "Found 2 tables."
    text = app.content_label.cget("text")
    assert "Sales" in text and "Menu" in text and "probably page layout" in text

def test_the_window_stays_responsive_and_locks_the_buttons_while_downloading(app, monkeypatch):
    started, gate = threading.Event(), threading.Event()
    def slow_fetch(url, cancel_event=None):
        started.set()
        gate.wait(5) # pretend the server is slow
        return PAGE
    run_fetch(app, monkeypatch, fetch=slow_fetch)
    assert started.wait(2)
    app.update() # the window can still process events
    assert app.busy
    assert str(app.fetch_button.cget("state")) == "disabled"
    assert str(app.cancel_button.cget("state")) == "normal"
    assert app.progress.winfo_manager() == "grid" # the progress bar is showing
    assert "Downloading from example.com" in app.status_var.get()
    gate.set()
    wait_until_idle(app)
    assert str(app.fetch_button.cget("state")) == "normal"
    assert str(app.cancel_button.cget("state")) == "disabled"
    assert app.progress.winfo_manager() == "" # and is hidden again

def test_pressing_fetch_again_while_busy_does_not_start_a_second_download(app, monkeypatch):
    calls, gate = [], threading.Event()
    def slow_fetch(url, cancel_event=None):
        calls.append(url)
        gate.wait(5)
        return PAGE
    run_fetch(app, monkeypatch, fetch=slow_fetch)
    app.on_fetch()
    app.on_fetch()
    gate.set()
    wait_until_idle(app)
    assert len(calls) == 1

def test_cancel_frees_the_window_at_once_and_a_late_answer_is_ignored(app, monkeypatch):
    stop_seen = threading.Event()
    def stubborn_fetch(url, cancel_event=None):
        cancel_event.wait(5) # waits until it is told to stop...
        stop_seen.set()
        return PAGE # ...but even so, hands back a page
    tables_before = list(app.tables)
    run_fetch(app, monkeypatch, fetch=stubborn_fetch, parse=lambda page: [Table("Late", ["A"], [["1"]])])
    app.update()
    app.on_cancel()
    assert not app.busy # free immediately, no waiting for the worker
    assert app.status_var.get() == "Cancelled."
    assert stop_seen.wait(2) # the worker really was told to stop
    for _ in range(20): # give any late message time to arrive
        app.update()
        time.sleep(0.01)
    assert app.status_var.get() == "Cancelled." # the stale answer did not overwrite it
    assert app.tables == tables_before

def test_cancel_when_nothing_is_running_does_nothing(app):
    before = app.status_var.get()
    app.on_cancel()
    assert app.status_var.get() == before

def test_a_download_can_be_cancelled_by_the_fetcher_itself(app, monkeypatch):
    def cancelled_fetch(url, cancel_event=None):
        raise FetchCancelled("Cancelled.")
    run_fetch(app, monkeypatch, fetch=cancelled_fetch)
    wait_until_idle(app)
    assert app.status_var.get() == "Cancelled."
    assert not app.status_is_error

def test_a_failed_download_shows_the_message_in_red(app, monkeypatch):
    def failing_fetch(url, cancel_event=None):
        raise FetchError("Page not found (404). Check the address.")
    run_fetch(app, monkeypatch, fetch=failing_fetch)
    wait_until_idle(app)
    assert app.status_var.get() == "Page not found (404). Check the address."
    assert app.status_is_error

def test_a_crash_in_the_parser_is_reported_not_swallowed_and_never_hangs(app, monkeypatch):
    def broken_parse(page):
        raise RuntimeError("boom")
    run_fetch(app, monkeypatch, parse=broken_parse)
    wait_until_idle(app)
    assert "Something went wrong" in app.status_var.get() and "RuntimeError" in app.status_var.get()
    assert app.status_is_error

def test_a_page_without_tables_says_so_and_clears_the_old_list(app, monkeypatch):
    run_fetch(app, monkeypatch, parse=lambda page: [Table("Old", ["A"], [["1"]])])
    wait_until_idle(app)
    run_fetch(app, monkeypatch, parse=lambda page: [])
    wait_until_idle(app)
    assert app.tables == []
    assert "No tables found" in app.status_var.get()
    assert not app.status_is_error
    assert "Old" not in app.content_label.cget("text")

def test_a_new_download_works_after_an_error(app, monkeypatch):
    run_fetch(app, monkeypatch, fetch=lambda u, cancel_event=None: (_ for _ in ()).throw(FetchError("nope")))
    wait_until_idle(app)
    run_fetch(app, monkeypatch, parse=lambda page: [Table("Ok", ["A"], [["1"]])])
    wait_until_idle(app)
    assert app.status_var.get() == "Found 1 table."
    assert not app.status_is_error

def test_an_answer_from_a_cancelled_job_cannot_leak_into_the_next_one(app, monkeypatch):
    release_old, release_new = threading.Event(), threading.Event()
    def late_fetch(url, cancel_event=None):
        release_old.wait(5)
        return FetchedPage(url=url, content=b"Stale", content_type="text/html")
    def fresh_fetch(url, cancel_event=None):
        release_new.wait(5)
        return FetchedPage(url=url, content=b"Fresh", content_type="text/html")
    def parse(page):                                     # the table is named after the page it came from
        return [Table(page.content.decode(), ["A"], [["1"]])]
    run_fetch(app, monkeypatch, fetch=late_fetch, parse=parse)
    app.update()
    app.on_cancel()
    release_old.set()
    time.sleep(0.3) # the old worker has now queued its answer
    run_fetch(app, monkeypatch, fetch=fresh_fetch, parse=parse)
    for _ in range(20): # the poll picks up the stale answer here
        app.update()
        time.sleep(0.01)
    assert app.busy # the stale answer did not end the new job
    assert [t.name for t in app.tables] != ["Stale"]
    release_new.set()
    wait_until_idle(app)
    assert [t.name for t in app.tables] == ["Fresh"]
    assert "Stale" not in app.content_label.cget("text")

def test_run_job_reports_cancelled_if_the_stop_signal_came_while_the_page_arrived(monkeypatch):
    import queue
    monkeypatch.setattr(app_module, "fetch", lambda url, cancel_event=None: PAGE)
    monkeypatch.setattr(app_module, "parse_page", lambda page: pytest.fail("should not parse after a cancel"))
    results, event = queue.Queue(), threading.Event()
    event.set()
    app_module.run_job(results, 7, "https://example.com", event)
    assert results.get_nowait() == ("cancelled", 7)

def test_cancel_tells_the_worker_to_stop(app, monkeypatch):
    seen = {}
    got_event = threading.Event()
    def fetch_that_records(url, cancel_event=None):
        seen["event"] = cancel_event
        got_event.set()
        cancel_event.wait(5)
        raise FetchCancelled("Cancelled.")
    run_fetch(app, monkeypatch, fetch=fetch_that_records)
    assert got_event.wait(2)
    assert not seen["event"].is_set()
    app.on_cancel()
    assert seen["event"].is_set()