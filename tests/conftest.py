"""Shared test setup: one main window for all the window tests."""
import pytest

@pytest.fixture(scope = "session")
def app():
    tk = pytest.importorskip("tkinter")
    from siphon_app.gui.app import SiphonApp
    try:
        window = SiphonApp()
    except tk.TclError:
        pytest.skip("no display available")
    window.withdraw()
    yield window
    window.destroy()