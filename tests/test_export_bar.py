"""Tests for siphon_app/gui/export_bar.py. The widget tests are skipped with no screen."""
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

from siphon_app.core.models import Table
from siphon_app.gui import export_bar as bar_module
from siphon_app.gui.export_bar import (
    CLEAN_OFF_TEXT, CLEAN_ON_TEXT, ExportBar, default_folder, export_label, run_export,
)

def table(name="Prices", rows=(("Alpha", "$1,234"), ("Beta", "$5"))):
    return Table(name, ["Name", "Price"], [list(r) for r in rows], source_url="https://example.com/p")

def wait_until(bar, condition, timeout=5.0):
    end = time.time() + timeout
    while not condition() and time.time() < end:
        bar.update()
        time.sleep(0.01)
    bar.update()
    assert condition(), "timed out waiting"

@pytest.fixture
def make_bar(app):
    """Build an ExportBar in its own little window. Returns (bar, notes, ticked) to poke at."""
    import ttkbootstrap as ttk
    windows = []

    def make(ticked=(), on_clean_change=None):
        top = ttk.Toplevel(app)
        top.withdraw()
        windows.append(top)
        notes, chosen = [], list(ticked)
        bar = ExportBar(top, get_tables=lambda: chosen,
                        notify=lambda text, error=False: notes.append((text, error)),
                        on_clean_change=on_clean_change)
        bar.pack()
        return bar, notes, chosen

    yield make
    for top in windows:
        top.destroy()

#the helpers
def test_export_label():
    assert export_label(0) == "Export"
    assert export_label(1) == "Export 1 table"
    assert export_label(4) == "Export 4 tables"

def test_default_folder_exists():
    assert Path(default_folder()).is_dir()

def test_run_export_reports_success_and_friendly_errors_through_the_queue(tmp_path):
    import queue
    results = queue.Queue()
    run_export(results, [table()], "json", str(tmp_path))
    kind, paths = results.get_nowait()
    assert kind == "saved" and paths[0].name == "Prices.json"
    run_export(results, [table()], "csv", "  ")
    assert results.get_nowait() == ("error", "Choose a folder to save into.")

def test_run_export_turns_a_surprise_crash_into_a_message(monkeypatch):
    import queue
    def boom(*args):
        raise ValueError("bug")
    monkeypatch.setattr(bar_module, "export_tables", boom)
    results = queue.Queue()
    run_export(results, [table()], "csv", "x")
    assert results.get_nowait() == ("error", "Something went wrong while saving (ValueError).")

#the widget
def test_starts_with_csv_cleaning_on_and_nothing_to_export(make_bar):
    bar, notes, _ = make_bar()
    assert bar.format_var.get() == "csv" and bar.clean_var.get() is True
    assert bar.export_button.cget("text") == "Export"
    assert str(bar.export_button.cget("state")) == "disabled"
    assert str(bar.open_button.cget("state")) == "disabled"
    assert bar.clean_label.cget("text") == CLEAN_ON_TEXT
    assert bar.folder_var.get() == default_folder()

def test_the_button_counts_the_ticked_tables(make_bar):
    bar, _, ticked = make_bar()
    ticked.extend([table("A"), table("B")])
    bar.refresh()
    assert bar.export_button.cget("text") == "Export 2 tables"
    assert str(bar.export_button.cget("state")) == "normal"
    ticked.pop()
    bar.refresh()
    assert bar.export_button.cget("text") == "Export 1 table"
    ticked.clear()
    bar.refresh()
    assert str(bar.export_button.cget("state")) == "disabled"

def test_the_hint_follows_the_chosen_format(make_bar):
    bar, _, _ = make_bar()
    assert "each table" in bar.format_hint.cget("text")
    bar.format_var.set("xlsx")
    bar._on_format()
    assert "workbook" in bar.format_hint.cget("text")
    bar.format_var.set("json")
    bar._on_format()
    assert ".json" in bar.format_hint.cget("text")

def test_changing_the_clean_box_tells_the_window(make_bar):
    seen = []
    bar, _, _ = make_bar(on_clean_change=seen.append)
    bar.clean_var.set(False)
    bar._on_clean()
    bar.clean_var.set(True)
    bar._on_clean()
    assert seen == [False, True]

def test_clean_text_can_be_set_or_reset(make_bar):
    bar, _, _ = make_bar()
    bar.set_clean_text("Turned 5 cells into numbers.")
    assert bar.clean_label.cget("text") == "Turned 5 cells into numbers."
    bar.set_clean_text()
    assert bar.clean_label.cget("text") == CLEAN_ON_TEXT
    bar.clean_var.set(False)
    bar.set_clean_text()
    assert bar.clean_label.cget("text") == CLEAN_OFF_TEXT

def test_exporting_saves_the_file_and_reports_it(make_bar, tmp_path):
    bar, notes, ticked = make_bar([table()])
    bar.format_var.set("json")
    bar.folder_var.set(str(tmp_path))
    bar.on_export()
    assert bar.busy and str(bar.export_button.cget("state")) == "disabled" # locked while saving
    assert notes[0] == ("Saving ...", False)
    wait_until(bar, lambda: not bar.busy)
    assert notes[-1] == (f"Saved Prices.json to {tmp_path}.", False)
    assert (tmp_path / "Prices.json").exists()
    assert bar.last_folder == tmp_path
    assert str(bar.open_button.cget("state")) == "normal"
    assert str(bar.export_button.cget("state")) == "normal"  # unlocked again

def test_exporting_with_nothing_ticked_explains_and_does_nothing(make_bar, tmp_path):
    bar, notes, _ = make_bar()
    bar.folder_var.set(str(tmp_path))
    bar.on_export()
    assert notes == [("Tick at least one table to export.", True)]
    assert not bar.busy and list(tmp_path.iterdir()) == []

def test_a_problem_while_saving_is_shown_as_an_error_and_the_bar_recovers(make_bar, tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("hi")
    bar, notes, _ = make_bar([table()])
    bar.folder_var.set(str(blocker))
    bar.on_export()
    wait_until(bar, lambda: not bar.busy)
    message, is_error = notes[-1]
    assert is_error and "Couldn't" in message
    assert str(bar.open_button.cget("state")) == "disabled" # nothing was saved
    assert str(bar.export_button.cget("state")) == "normal"

def test_a_blank_folder_is_an_error_not_a_crash(make_bar):
    bar, notes, _ = make_bar([table()])
    bar.folder_var.set("   ")
    bar.on_export()
    wait_until(bar, lambda: not bar.busy)
    assert notes[-1] == ("Choose a folder to save into.", True)

def test_pressing_export_twice_quickly_saves_only_once(make_bar, tmp_path, monkeypatch):
    gate, calls = threading.Event(), []
    real = bar_module.export_tables

    def slow(tables, fmt, folder):
        calls.append(1)
        gate.wait(5)
        return real(tables, fmt, folder)

    monkeypatch.setattr(bar_module, "export_tables", slow)
    bar, notes, _ = make_bar([table()])
    bar.format_var.set("json")
    bar.folder_var.set(str(tmp_path))
    bar.on_export()
    bar.on_export() # ignored: the first one is still running
    gate.set()
    wait_until(bar, lambda: not bar.busy)
    assert calls == [1] and [p.name for p in tmp_path.iterdir()] == ["Prices.json"]

def test_the_window_stays_alive_while_a_save_runs(make_bar, tmp_path, monkeypatch):
    gate = threading.Event()
    real = bar_module.export_tables
    monkeypatch.setattr(bar_module, "export_tables",
                        lambda t, f, d: (gate.wait(5), real(t, f, d))[1])
    bar, _, _ = make_bar([table()])
    bar.format_var.set("json")
    bar.folder_var.set(str(tmp_path))
    bar.on_export()
    for _ in range(5):
        bar.update() # would hang if saving blocked the window
        time.sleep(0.01)
    assert bar.busy
    gate.set()
    wait_until(bar, lambda: not bar.busy)

def test_browse_fills_in_the_chosen_folder_and_cancel_keeps_the_old_one(make_bar, monkeypatch, tmp_path):
    bar, _, _ = make_bar()
    bar.folder_var.set("before")
    monkeypatch.setattr(bar_module.filedialog, "askdirectory", lambda **kw: str(tmp_path))
    bar.browse()
    assert Path(bar.folder_var.get()) == tmp_path
    monkeypatch.setattr(bar_module.filedialog, "askdirectory", lambda **kw: "")      # pressed Cancel
    bar.browse()
    assert Path(bar.folder_var.get()) == tmp_path

def test_browse_starts_in_the_current_folder(make_bar, monkeypatch, tmp_path):
    bar, _, _ = make_bar()
    bar.folder_var.set(str(tmp_path))
    seen = {}
    monkeypatch.setattr(bar_module.filedialog, "askdirectory", lambda **kw: seen.update(kw) or "")
    bar.browse()
    assert seen["initialdir"] == str(tmp_path)

def test_open_folder_button_opens_the_last_saved_folder(make_bar, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(bar_module, "open_folder", opened.append)
    bar, notes, _ = make_bar([table()])
    bar.on_open() # nothing saved yet: nothing happens
    assert opened == []
    bar.format_var.set("json")
    bar.folder_var.set(str(tmp_path))
    bar.on_export()
    wait_until(bar, lambda: not bar.busy)
    bar.on_open()
    assert opened == [tmp_path]

def test_open_folder_failure_is_reported(make_bar, monkeypatch, tmp_path):
    def fail(folder):
        raise OSError("no file manager")
    monkeypatch.setattr(bar_module, "open_folder", fail)
    bar, notes, _ = make_bar([table()])
    bar.last_folder = tmp_path
    bar.on_open()
    assert notes[-1] == (f"Couldn't open {tmp_path}.", True)

def test_destroying_the_bar_mid_save_leaves_no_stray_timer(app, tmp_path, monkeypatch):
    import ttkbootstrap as ttk
    gate = threading.Event()
    real = bar_module.export_tables
    monkeypatch.setattr(bar_module, "export_tables", lambda t, f, d: (gate.wait(5), real(t, f, d))[1])
    errors = []
    monkeypatch.setattr(app, "report_callback_exception", lambda *info: errors.append(info))
    top = ttk.Toplevel(app)
    top.withdraw()
    bar = ExportBar(top, get_tables=lambda: [table()])
    bar.pack()
    bar.format_var.set("json")
    bar.folder_var.set(str(tmp_path))
    bar.on_export()
    assert bar._poll_id is not None
    bar.destroy()
    top.destroy()
    gate.set()
    for _ in range(10):
        app.update() # a leftover timer would complain here
        time.sleep(0.02)
    assert errors == []