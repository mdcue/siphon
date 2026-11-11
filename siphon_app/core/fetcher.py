"""
siphon/core/fetcher.py

Downloads a web page safely: tidy the address, use timeouts, retry a few times,
stop if the page is too big or too slow, allow Cancel, and turn every failure into a
plain-English message. Nothing here knows about windows or buttons.
"""
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import DecodeError, ProtocolError, ReadTimeoutError
from urllib3.exceptions import SSLError as Urllib3SSLError
from urllib3.util.retry import Retry

from siphon_app import __url__, __version__

# ---- limits (all in one place so they are easy to change) ------------------
# Without these, one huge or stuck page could freeze the app or eat all the memory.
CONNECT_TIMEOUT = 5            # seconds to wait for the server to pick up
READ_TIMEOUT = 20              # seconds of silence allowed between bytes
MAX_SECONDS = 60               # hard ceiling for the whole download
MAX_BYTES = 20 * 1024 * 1024   # 20 MB, far more than a normal page
CHUNK_SIZE = 64 * 1024         # take at most 64 KB per read
FALLBACK_CHUNK = 8 * 1024      # only used with a very old urllib3 (see _chunks)
HTML_TYPES = ("", "text/html", "application/xhtml+xml")  # "" = server didn't say

class FetchError(Exception):
    """A download problem. str(error) is always safe to show to the user."""

class FetchCancelled(FetchError):
    """The user pressed Cancel. Not really an error, so the GUI can tell it apart."""

@dataclass
class FetchedPage:
    url: str            # final address, after any redirects
    content: bytes      # raw bytes; BeautifulSoup works out the encoding itself
    content_type: str   # e.g. "text/html; charset=utf-8" (may be empty)
    note: str = ""      # something worth telling the user, e.g. "Used the copy from 40 seconds ago."

def normalize_url(raw: str) -> str:
    """Tidy what the user typed into a usable http(s) address, or raise FetchError."""
    text = raw.strip()
    if not text:
        raise FetchError("Please enter a web address.")
    if "://" not in text:
        # Things like "mailto:me@x.com" or "javascript:..." have a scheme but no "//".
        # "localhost:8000" and "example.com:8080" are fine: a digit follows the colon.
        if re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:(?!\d)", text):
            raise FetchError("Only http and https addresses are supported.")
        text = "https://" + text          # "example.com" -> "https://example.com"

    try:
        parsed = urlparse(text)
        host = parsed.hostname
        _ = parsed.port                   # raises ValueError if the port isn't a number
    except ValueError:
        raise FetchError("That doesn't look like a web address.") from None

    if parsed.scheme not in ("http", "https"):
        raise FetchError("Only http and https addresses are supported.")
    if not host or re.search(r"\s", parsed.netloc):
        raise FetchError("That doesn't look like a web address.")
    return text

def make_session(user_agent: str | None = None) -> requests.Session:
    """
    A requests Session that retries temporary failures a few times.

    Retries are there because sites hiccup now and then (a dropped connection, a 503),
    and trying again quietly beats showing an error for something that fixes itself.
    One Session also reuses the connection between requests.
    """
    session = requests.Session()
    session.headers["User-Agent"] = user_agent or f"Mozilla/5.0 (compatible; siphon/{__version__}; +{__url__})"
    session.headers["Accept"] = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"

    retry = Retry(
        total=3,                              # never more than 3 retries overall
        connect=1,                            # 1 retry if we can't connect
        read=1,                               # 1 retry if the server goes quiet
        status=2,                             # 2 retries on the status codes below
        backoff_factor=0.5,                   # wait a little longer before each retry
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,                # hand back the last response so we can explain it
        respect_retry_after_header=False,     # a server saying "wait 5 minutes" must not freeze the app
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def fetch(
    url: str,
    *,
    session: requests.Session | None = None,
    timeout: tuple[float, float] = (CONNECT_TIMEOUT, READ_TIMEOUT),
    cancel_event: threading.Event | None = None,
) -> FetchedPage:
    """Download one page. Raises FetchError (or FetchCancelled) with a friendly message.

    Pass your own session to reuse it (or to fake it in tests); otherwise we make one and close it.
    """
    clean_url = normalize_url(url)
    host = urlparse(clean_url).hostname

    own_session = session is None
    if own_session:
        session = make_session()
    try:
        return _download(session, clean_url, host, timeout, cancel_event)
    finally:
        if own_session:
            session.close()

#internals
def _check_cancel(cancel_event: threading.Event | None) -> None:
    """Stop right now if the user pressed Cancel."""
    if cancel_event is not None and cancel_event.is_set():
        raise FetchCancelled("Cancelled.")

def _too_big() -> FetchError:
    """The error for a page over MAX_BYTES (used in two places, so it lives here)."""
    return FetchError(
        f"That page is bigger than {MAX_BYTES // (1024 * 1024)} MB, "
        "which is more than siphon will download."
    )

def _chunks(response):
    """Yield the page body in pieces, handing over whatever has arrived so far.

    iter_content() would wait for a whole chunk, so a slow server could keep us
    stuck for a long time without ever reaching our cancel and time checks.
    read1() returns as soon as *some* bytes are there, so those checks run often.
    """
    read1 = getattr(response.raw, "read1", None)
    if read1 is None:                      # old urllib3 without read1: still works, just less snappy
        yield from response.iter_content(FALLBACK_CHUNK)
        return
    try:
        while True:
            chunk = read1(CHUNK_SIZE, decode_content=True)
            if not chunk:                  # empty bytes = the page has ended
                return
            yield chunk
    # requests normally translates these low-level errors for us. Because we read
    # the raw stream, we translate them ourselves into the same requests errors.
    except ReadTimeoutError as error:
        raise requests.exceptions.ReadTimeout(error) from None
    except ProtocolError as error:
        raise requests.exceptions.ChunkedEncodingError(error) from None
    except DecodeError as error:
        raise requests.exceptions.ContentDecodingError(error) from None
    except Urllib3SSLError as error:
        raise requests.exceptions.SSLError(error) from None

def _status_message(code: int, host: str) -> str:
    """Turn an HTTP error code into a sentence a non-programmer can act on."""
    known = {
        400: "The site didn't understand the request (400).",
        401: "That page needs a login (401), which siphon can't do.",
        403: f"{host} refused access (403). It may block scrapers or need a login.",
        404: "Page not found (404). Check the address.",
        429: f"{host} says there were too many requests (429). Wait a bit and try again.",
    }
    if code in known:
        return known[code]
    if code >= 500:
        return f"{host} had a server problem ({code}). Try again later."
    return f"The site answered with error {code}."

def _download(session, url, host, timeout, cancel_event) -> FetchedPage:
    """
    Do the actual download, with all the safety checks.

    We stream the body (instead of grabbing it in one go) so we can cancel, enforce the
    size cap and the time limit while it arrives. Every requests error is caught at the
    bottom and re-raised as a FetchError with a friendly message.
    """
    _check_cancel(cancel_event)
    try:
        # stream=True: get the headers first and only then decide whether to
        # download the body. The "with" closes the connection however we leave.
        with session.get(url, stream=True, timeout=timeout) as response:
            if response.status_code >= 400:
                raise FetchError(_status_message(response.status_code, host))

            content_type = response.headers.get("Content-Type", "")
            kind = content_type.split(";")[0].strip().lower()
            if kind not in HTML_TYPES:
                raise FetchError(f"That link isn't a web page (the server says it is '{kind}').")

            # Content-Length lets us refuse a huge page before downloading any of it
            declared = response.headers.get("Content-Length", "")
            if declared.isdigit() and int(declared) > MAX_BYTES:
                raise _too_big()

            data = bytearray()                # we count bytes as they arrive, since the header can lie or be missing
            started = time.monotonic()
            for chunk in _chunks(response):
                _check_cancel(cancel_event)
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise _too_big()
                if time.monotonic() - started > MAX_SECONDS:
                    raise FetchError(f"The download took longer than {MAX_SECONDS} seconds, so I stopped.")

            return FetchedPage(url=response.url, content=bytes(data), content_type=content_type)

    # Order matters: ConnectTimeout and SSLError are special cases of broader
    # errors, so they must be caught before the broader ones.
    except requests.exceptions.ConnectTimeout:
        raise FetchError(f"Couldn't reach {host} within {timeout[0]:g} seconds.") from None
    except requests.exceptions.Timeout:
        raise FetchError(f"{host} took too long to send the page.") from None
    except requests.exceptions.SSLError:
        raise FetchError("The site's security certificate couldn't be verified, so I didn't connect.") from None
    except requests.exceptions.TooManyRedirects:
        raise FetchError("The site keeps redirecting in a loop.") from None
    except (requests.exceptions.InvalidURL, requests.exceptions.InvalidSchema,
            requests.exceptions.MissingSchema):
        raise FetchError("That doesn't look like a web address.") from None
    except requests.exceptions.ChunkedEncodingError:
        raise FetchError("The connection dropped while the page was downloading.") from None
    except requests.exceptions.ConnectionError as error:
        # With retries switched on, requests wraps a read timeout inside a plain
        # ConnectionError, so look inside to find the real cause.
        cause = error.args[0] if error.args else None
        if isinstance(cause, ReadTimeoutError) or isinstance(getattr(cause, "reason", None), ReadTimeoutError):
            raise FetchError(f"{host} took too long to send the page.") from None
        raise FetchError(f"Couldn't connect to {host}. Check the address and your internet connection.") from None
    except requests.exceptions.RequestException as error:
        raise FetchError(f"Something went wrong while downloading the page: {error}") from None

if __name__ == "__main__":
    # Quick manual check from the terminal, no GUI needed:
    #   python -m siphon.core.fetcher http://localhost:8000/index.html
    import sys

    for address in sys.argv[1:]:
        try:
            page = fetch(address)
            print("OK   ", page.url, f"({len(page.content)} bytes, {page.content_type or 'no content type'})")
        except FetchError as error:
            print("ERROR", error)