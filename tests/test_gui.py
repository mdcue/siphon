"""Smoke tests for the main window. They are skipped on a machine with no screen."""

import pytest

tk = pytest.importorskip("tkinter")

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

def test_window_starts_ready_with_the_light_theme(app):
    assert app.title() == "siphon."
    assert app.status_var.get() == READY_TEXT
    assert app.style.theme.name == LIGHT_THEME
    assert app.style.theme_mode == "light"
    assert not app.status_is_error

def test_a_bad_address_shows_the_reason_in_the_status_bar(app):
    app.url_var.set("mailto:someone@example.com")
    app.on_fetch()
    assert "http and https" in app.status_var.get()
    assert app.status_is_error

def test_an_empty_address_is_rejected(app):
    app.url_var.set("   ")
    app.on_fetch()
    assert app.status_var.get() != READY_TEXT
    assert app.status_is_error

def test_a_good_address_is_tidied_and_accepted(app):
    app.url_var.set("  example.com/data ")
    app.on_fetch()
    assert app.url_var.get() == "https://example.com/data" # https:// added, spaces gone
    assert "https://example.com/data" in app.status_var.get()
    assert not app.status_is_error # the red from before is cleared

def test_theme_button_switches_to_dark_and_back(app):
    app.toggle_theme()
    assert app.style.theme_mode == "dark"
    assert app.theme_button.cget("text") == "Light"  # the button now offers the other theme
    app.toggle_theme()
    assert app.style.theme_mode == "light"
    assert app.theme_button.cget("text") == "Dark"

def test_enter_in_the_url_box_fetches(app):
    assert app.url_entry.bind("<Return>")