"""Tests for make_notices.py: the licence list that ships with the program."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def notices(tmp_path_factory):
    target = tmp_path_factory.mktemp("notices") / "deep" / "THIRD_PARTY_NOTICES.txt"      # the folder doesn't exist yet
    result = subprocess.run([sys.executable, str(ROOT / "make_notices.py"), str(target)],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return target.read_text(encoding="utf-8")


# every library siphon imports is listed, with its licence text and not just a name
@pytest.mark.parametrize("name", ["requests", "beautifulsoup4", "lxml", "openpyxl", "platformdirs", "ttkbootstrap"])
def test_every_direct_library_is_listed(notices, name):
    assert f"  - {name} " in notices


# libraries those need (found automatically) are listed too
def test_libraries_that_the_libraries_need_are_listed_too(notices):
    assert "  - urllib3 " in notices and "  - certifi " in notices


def test_licence_texts_are_included(notices):
    assert "Apache License" in notices                    # requests
    assert "Permission is hereby granted" in notices      # the MIT ones
    assert "Mozilla Public License" in notices            # certifi


# the bundled things that are not pip packages are explained
def test_the_extras_are_mentioned(notices):
    for word in ("PyInstaller", "Tcl/Tk", "libiconv", "certifi"):
        assert word in notices


def test_the_project_has_its_own_licence_and_security_files():
    assert "MIT License" in (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Report a vulnerability" in (ROOT / "SECURITY.md").read_text(encoding="utf-8")
