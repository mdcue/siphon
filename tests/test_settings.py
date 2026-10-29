"""Tests for siphon_app/settings.py. Nothing here needs a screen."""
import json
import os
from pathlib import Path

import pytest

from siphon_app import settings as settings_module
from siphon_app.settings import (
    MAX_RECENT, Settings, load_settings, remember_url, save_settings, settings_path,
)

def write(path, data):
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")

#defaults and round trips
def test_defaults_are_sensible():
    s = Settings()
    assert (s.export_folder, s.export_format, s.clean_numbers, s.theme) == ("", "csv", True, "light")
    assert (s.window_width, s.window_height, s.recent_urls) == (1000, 640, [])

def test_the_settings_file_lives_in_a_siphon_folder_and_is_not_created_by_asking():
    path = settings_path()
    assert path.name == "settings.json" and path.parent.name == "Siphon"

def test_a_missing_file_gives_the_defaults(tmp_path):
    assert load_settings(tmp_path / "nothing.json") == Settings()

def test_everything_survives_a_save_and_a_load(tmp_path):
    original = Settings("C:/Data/Out", "xlsx", False, "dark", 1234, 777, ["https://a.com", "https://b.com/x?y=1"])
    path = tmp_path / "settings.json"
    assert save_settings(original, path) is True
    assert load_settings(path) == original

def test_non_english_text_survives(tmp_path):
    original = Settings(export_folder="C:/Users/\u00c9mile/\u6587\u4ef6", recent_urls=["https://\u4f8b\u3048.jp/\u8868"])
    path = tmp_path / "settings.json"
    save_settings(original, path)
    assert load_settings(path) == original

def test_the_file_is_readable_json_with_a_version(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["export_format"] == "csv"

# damaged files never crash anything
@pytest.mark.parametrize("content", ["", "{", "not json at all", "[1, 2, 3]", "null", '"text"', "42", "\x00\x01\x02"])
def test_a_damaged_or_odd_file_gives_the_defaults(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8", errors="ignore")
    assert load_settings(path) == Settings()

def test_a_file_that_is_not_text_at_all_gives_the_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_bytes(b"\xff\xfe\x00\x80\x81")
    assert load_settings(path) == Settings()

def test_a_folder_where_the_file_should_be_gives_the_defaults(tmp_path):
    (tmp_path / "settings.json").mkdir()
    assert load_settings(tmp_path / "settings.json") == Settings()

def test_one_bad_value_does_not_spoil_the_good_ones(tmp_path):
    path = tmp_path / "settings.json"
    write(path, {"export_folder": 5, "export_format": "xlsx", "clean_numbers": "yes", "theme": "dark",
                "window_width": "wide", "window_height": 700, "recent_urls": "https://a.com"})
    s = load_settings(path)
    assert s.export_folder == "" # wrong type: default
    assert s.export_format == "xlsx" # fine: kept
    assert s.clean_numbers is True # wrong type: default
    assert s.theme == "dark" # fine: kept
    assert s.window_width == 1000 # wrong type: default
    assert s.window_height == 700 # fine: kept
    assert s.recent_urls == [] # a string instead of a list: default

@pytest.mark.parametrize("key, value, default", [
    ("export_format", "docx", "csv"), ("export_format", None, "csv"), ("export_format", ["csv"], "csv"),
    ("theme", "purple", "light"), ("theme", 1, "light"), ("theme", "DARK", "light"),
])
def test_unknown_choices_fall_back(tmp_path, key, value, default):
    path = tmp_path / "settings.json"
    write(path, {key: value})
    assert getattr(load_settings(path), key) == default

@pytest.mark.parametrize("value", [True, False, 479, 0, -5, 10_001, 1e9, 1000.5, None, "1000", [1000]])
def test_silly_window_sizes_fall_back(tmp_path, value):
    path = tmp_path / "settings.json"
    write(path, {"window_width": value, "window_height": value})
    s = load_settings(path)
    assert (s.window_width, s.window_height) == (1000, 640)

def test_sizes_at_the_limits_are_accepted(tmp_path):
    path = tmp_path / "settings.json"
    write(path, {"window_width": 760, "window_height": 480})
    s = load_settings(path)
    assert (s.window_width, s.window_height) == (760, 480)
    write(path, {"window_width": 10_000, "window_height": 10_000})
    s = load_settings(path)
    assert (s.window_width, s.window_height) == (10_000, 10_000)

def test_unknown_keys_are_ignored(tmp_path):
    path = tmp_path / "settings.json"
    write(path, {"theme": "dark", "future_setting": {"a": 1}})
    assert load_settings(path).theme == "dark"

def test_the_folder_text_is_trimmed(tmp_path):
    path = tmp_path / "settings.json"
    write(path, {"export_folder": "  C:/Out  "})
    assert load_settings(path).export_folder == "C:/Out"

def test_recent_addresses_are_cleaned_when_loaded(tmp_path):
    path = tmp_path / "settings.json"
    many = [f"https://site{i}.com" for i in range(30)]
    write(path, {"recent_urls": ["https://a.com", 5, None, "", "   ", ["x"], "https://a.com", "https://b.com"] + many})
    urls = load_settings(path).recent_urls
    assert urls[:2] == ["https://a.com", "https://b.com"] # junk and repeats gone, order kept
    assert len(urls) == MAX_RECENT

# the recent list
def test_newest_address_goes_to_the_top():
    s = Settings()
    remember_url(s, "https://a.com")
    remember_url(s, "https://b.com")
    assert s.recent_urls == ["https://b.com", "https://a.com"]

def test_an_address_seen_again_moves_up_instead_of_repeating():
    s = Settings(recent_urls=["https://c.com", "https://b.com", "https://a.com"])
    remember_url(s, "https://a.com")
    assert s.recent_urls == ["https://a.com", "https://c.com", "https://b.com"]

def test_the_list_never_grows_past_the_limit():
    s = Settings()
    for i in range(MAX_RECENT + 5):
        remember_url(s, f"https://site{i}.com")
    assert len(s.recent_urls) == MAX_RECENT
    assert s.recent_urls[0] == f"https://site{MAX_RECENT + 4}.com"
    assert "https://site0.com" not in s.recent_urls # the oldest fell off

@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_blank_addresses_are_not_remembered(blank):
    s = Settings(recent_urls=["https://a.com"])
    remember_url(s, blank)
    assert s.recent_urls == ["https://a.com"]

def test_spaces_around_an_address_are_trimmed():
    s = Settings()
    remember_url(s, "  https://a.com  ")
    assert s.recent_urls == ["https://a.com"]

#saving safely
def test_saving_creates_the_folder(tmp_path):
    path = tmp_path / "deep" / "er" / "settings.json"
    assert save_settings(Settings(), path) is True and path.exists()

def test_saving_twice_replaces_the_old_file_and_leaves_no_temporary_one(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(theme="dark"), path)
    save_settings(Settings(theme="light"), path)
    assert load_settings(path).theme == "light"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json"]

def test_a_failed_save_returns_false_and_never_raises(tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("hi")
    assert save_settings(Settings(), blocker / "settings.json") is False # the "folder" is a file

def test_a_crash_while_swapping_keeps_the_old_file_and_cleans_up(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    save_settings(Settings(theme="dark"), path)

    def broken_replace(source, target):
        raise PermissionError("locked")

    monkeypatch.setattr(os, "replace", broken_replace)
    assert save_settings(Settings(theme="light"), path) is False
    monkeypatch.undo()
    assert load_settings(path).theme == "dark" # the old file is untouched
    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json"] # no leftover .tmp

def test_default_path_is_used_when_none_is_given(tmp_path, monkeypatch):
    target = tmp_path / "chosen.json"
    monkeypatch.setattr(settings_module, "settings_path", lambda: target)
    assert save_settings(Settings(theme="dark")) is True
    assert load_settings().theme == "dark"
    assert target.exists()