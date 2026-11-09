"""Reads a saved web page so its tables can be used like a downloaded one."""
from pathlib import Path

from siphon_app.core.fetcher import MAX_BYTES, FetchedPage, FetchError

HTML_EXTENSIONS = (".html", ".htm", ".xhtml")

def read_html_file(path: str | Path) -> FetchedPage:
    """Read the file as a FetchedPage, or raise FetchError."""
    path = Path(path)
    if path.is_dir():
        raise FetchError("That is a folder, not a saved web page.")
    if not path.exists():
        raise FetchError("That file doesn't exist. Check the path.")
    if path.suffix.lower() not in HTML_EXTENSIONS:
        kind = path.suffix.lower() or "no extension"
        raise FetchError(f"siphon opens saved web pages (.html or .htm), not files with {kind}.")
    limit_text = f"That file is bigger than {MAX_BYTES // (1024 * 1024)} MB, which is more than siphon will open."
    try:
        if path.stat().st_size > MAX_BYTES:
            raise FetchError(limit_text)
        with open(path, "rb") as handle:
            content = handle.read(MAX_BYTES + 1) # one extra byte tells us if the file grew while reading
    except PermissionError:
        raise FetchError("Couldn't read that file. It may be open in another program or protected.") from None
    except OSError as error:
        raise FetchError(f"Couldn't read that file: {error.strerror or error}.") from None
    if len(content) > MAX_BYTES:
        raise FetchError(limit_text)
    return FetchedPage(url=path.resolve().as_uri(), content=content, content_type="text/html")
