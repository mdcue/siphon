"""Shared test setup: one main window for all the window tests."""
import pytest

@pytest.fixture(scope="session")
def app(tmp_path_factory):
    tk = pytest.importorskip("tkinter")
    from siphon_app.gui.app import SiphonApp
    try:
        #a throwaway settings file, so the tests never read or change YOUR real settings
        window = SiphonApp(tmp_path_factory.mktemp("settings") / "settings.json")
    except tk.TclError:
        pytest.skip("no display available")
    window.withdraw() # don't flash a window during the tests
    yield window
    window.destroy()