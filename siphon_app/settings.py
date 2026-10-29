"""
siphon_app/settings.py

What the app remembers between runs: where you last saved files, the format, whether
"Clean numbers" was on, the theme, the window size and your recent web addresses.

It is stored as a small JSON file in your own user folder. Reading it never crashes the
app: a missing, damaged or hand-edited file simply falls back to sensible defaults, one
setting at a time. Nothing here knows about windows or buttons.
"""
import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

from platformdirs import user_config_dir

from siphon_app.core.pipeline import FORMATS

MAX_RECENT = 10  # how many recent addresses to keep
MIN_WIDTH, MIN_HEIGHT = 760, 480  # the smallest window the app allows
MAX_SIZE = 10_000 # anything bigger in the file is obviously wrong
THEMES = ("light", "dark")
FILE_VERSION = 1  # written into the file so future versions can upgrade old ones


@dataclass
class Settings:
    export_folder: str = "" # "" means "use the Downloads folder"
    export_format: str = "csv"
    clean_numbers: bool = True
    theme: str = "light"
    window_width: int = 1000
    window_height: int = 640
    recent_urls: list[str] = field(default_factory=list)

def settings_path() -> Path:
    """Where the file lives: C:\\Users\\<you>\\AppData\\Local\\Siphon\\settings.json on Windows."""
    return Path(user_config_dir("Siphon", appauthor=False)) / "settings.json"

# checking one value at a time
# Each takes whatever was in the file and returns something safe to use.
def _text(value, default: str) -> str:
    return value if isinstance(value, str) else default

def _choice(value, allowed, default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default

def _flag(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default

def _size(value, minimum: int, default: int) -> int:
    # bool is a kind of int in Python, so True would sneak through without this check
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= MAX_SIZE:
        return default
    return value

def _urls(value) -> list[str]:
    """Keep only non-empty text, drop repeats (keeping the first), and cap the length."""
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip() and item not in result:
            result.append(item)
    return result[:MAX_RECENT]

#loading and saving
def load_settings(path: str | Path | None = None) -> Settings:
    """Read the file. Anything missing or wrong falls back to its default."""
    defaults = Settings()
    try:
        with open(path or settings_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError): # no file yet, unreadable, or not valid JSON
        return defaults
    if not isinstance(data, dict):
        return defaults
    return Settings(
        export_folder=_text(data.get("export_folder"), defaults.export_folder).strip(),
        export_format=_choice(data.get("export_format"), FORMATS, defaults.export_format),
        clean_numbers=_flag(data.get("clean_numbers"), defaults.clean_numbers),
        theme=_choice(data.get("theme"), THEMES, defaults.theme),
        window_width=_size(data.get("window_width"), MIN_WIDTH, defaults.window_width),
        window_height=_size(data.get("window_height"), MIN_HEIGHT, defaults.window_height),
        recent_urls=_urls(data.get("recent_urls")),
    )

def save_settings(settings: Settings, path: str | Path | None = None) -> bool:
    """
    Write the file. Returns True if it worked. Remembering things is a convenience, so a
    failure (a read-only disk, say) must never get in the person's way: it just returns False.

    The text goes into a temporary file first and is then swapped into place, so a crash or
    power cut half way through can never leave a half-written settings file behind.
    """
    target = Path(path or settings_path())
    temporary = target.with_name(target.name + ".tmp")
    data = {"version": FILE_VERSION, **{f.name: getattr(settings, f.name) for f in fields(settings)}}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, target) # one step, so it is all-or-nothing
        return True
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        return False

def remember_url(settings: Settings, url: str) -> None:
    """Put an address at the top of the recent list (moving it up if it was already there)."""
    url = url.strip()
    if not url:
        return
    settings.recent_urls = [url] + [u for u in settings.recent_urls if u != url]
    del settings.recent_urls[MAX_RECENT:]