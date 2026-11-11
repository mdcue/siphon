"""
tests/test_icon.py

The icon file ships with the app and has the sizes Windows asks for.
"""
from PIL import Image

from siphon_app.gui.app import ICON_PATH


def test_icon_file_exists():
    assert ICON_PATH.is_file()


def test_icon_has_the_sizes_windows_asks_for():
    with Image.open(ICON_PATH) as icon:
        sizes = icon.info["sizes"]
    for size in [(16, 16), (32, 32), (48, 48), (256, 256)]:
        assert size in sizes