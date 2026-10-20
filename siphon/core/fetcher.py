"""
siphon/core/fetcher.py

Downloads a webpage safely: tidy address, timeouts, a few retries,
size and time limits, cancel support, and plain-English error messages.
Nothing here knows about windows or buttons.
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

from siphon import __version__

#limits
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 20
MAX_SECONDS = 60
MAX_BYTES = 20 * 1024 * 1024
CHUNK_SIZE = 64 * 1024
FALLBACK_CHUNK = 8 * 1024
HTML_TYPES = ("", "text/html", "application/xhtml+xml")

class FetchError(Exception):
    """A download problem. str(error) is always safe to show to the user."""

class FetchCancelled(FetchError):
    """The user pressed cancel. Not really an error, so the GUI can tell it apart."""

@dataclass
class FetchedPage:
    url: str #this is the final address, after any redirects
    content: bytes #raw bytes; cause BeautifulSoup works out the encoding on its own
    content_type: str


def normalize_url(raw: str) -> str:
    """Tidy what the user typed into a usable http(s) address, or raise FetchError."""
    text = raw.strip()
    if not text:
        raise FetchError("Please enter a web address.")
    if "://" not in text:
        #Things like "mailto:me@x.com" or "javascript..." have a scheme but no "//".
        #"'localhost:8000" is fine: a digit follows the colon
        if re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:(?!\d)", text):
            raise FetchError("Only http and https addresses are supported.")
        text = "https://" + text
    
    try:
        parsed = urlparse(text)
        host = parsed.hostname
        _ = parsed.port #this will raise ValueError if the port isn't a number
    except ValueError:
        raise FetchError("That doesn't look like a web address.") from None
    
    if parsed.scheme not in ("http", "https"):
        raise FetchError("Only http and https addresses are supported.")
    if not host or re.search(r"\s", parsed.netloc):
        raise FetchError("That doesn't look like a web address.")
    return text

def make_session(user_agent: str | None = None) -> requests.Session:
    """A requests Session that retries temporary failures a couple of times."""
    session = requests.Session()
    session.headers["User-Agent"] = user_agent or f"Mozilla/5.0 (compatible; siphon/{__version__})"
    session.headers["Accept"] = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
    
    retry = Retry(
        total = 3,
        connect = 1,
        read = 1,
        status = 2,
        backoff_factor = 0.5,
        status_forcelist = (429, 500, 502, 503, 504),
        allowed_methods = ("GET",),
        raise_on_status = False,
        respect_retry_after_header = False,
    )
    adapter = HTTPAdapter(max_retries = retry)
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
    """Download one page. Raises FetchError (or FetchCancelled) with a friendly message."""
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

#internal working

def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise FetchCancelled("Cancelled.")

def _too_big() -> FetchError:
    return FetchError(
        f"That page is bigger than {MAX_BYTES // (1024 * 1024)} MB,"
        "which is more than siphon will download."
    )

def _chunks(response):
    """Yield the page body in pieces, handing over whatever has arrived so far.
    
    iter_content() would wait for a whole chunk, so a slow server could keep us
    stuck for a long time without ever reaching our cancel and time checks.
    read1() returns as soon as *some* bytes are there, so those checks run often.
    """
    read1 = getattr(response.raw, "read1", None)
    if read1 is None:
        yield from response.iter_content(FALLBACK_CHUNK)
        return
    try:
        while True:
            chunk = read1(CHUNK_SIZE, decode_content = True)
            if not chunk:
                return
            yield chunk
    except ReadTimeoutError as error:
        raise requests.exceptions.ReadTimeout(error) from None
    except ProtocolError as error:
        raise requests.exceptions.ChunkedEncodingError(error) from None
    except DecodeError as error:
        raise requests.exceptions.ContentDecodingError(error) from None
    except Urllib3SSLError as error:
        raise requests.exceptions.SSLError(error) from None

def _status_message(code: int, host: str) -> str:
    known = {
        400: "The site didn't understand the request (400).",
        401: "That page needs a login (401), which siphon can't do.",
        403: f"{host} refused access (403). It may block scrapers or require login.",
        404: "Page not found (404). Check the address.",
        429: f"{host} says there were too many requests (429). Wait a bit and try again.",
    }
    if code in known:
        return known[code]
    if code >= 500:
        return f"{host} had a server problem ({code}). Try again later."
    return f"The site answered with error {code}."

def _download(session, url, host, timeout, cancel_event) -> FetchedPage:
    _check_cancel(cancel_event)
    try:
        with session.get(url, stream = True, timeout = timeout) as response:
            if response.status_code >= 400:
                raise FetchError(_status_message(response.status_code, host))
            
            content_type = response.headers.get("Content-Type", "")
            kind = content_type.split(";")[0].strip().lower()
            if kind not in HTML_TYPES:
                raise FetchError(f"That link isn't a web page (the server says it is '{kind}').")
            
            declared = response.headers.get("Content-Length", "")
            if declared.isdigit() and int(declared) > MAX_BYTES:
                raise _too_big()
            
            data = bytearray()
            started = time.monotonic()
            for chunk in _chunks(response):
                _check_cancel(cancel_event)
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise _too_big()
                if time.monotonic() - started > MAX_SECONDS:
                    raise FetchError(f"The download took longer than {MAX_SECONDS} seconds, so I stopped.")
            
            return FetchedPage(url = response.url, content = bytes(data), content_type = content_type)
    
    except requests.exceptions.ConnectTimeout:
        raise FetchError(f"Couldn't reach {host} within {timeout[0]:g} seconds.") from None
    except requests.exceptions.Timeout:
        raise FetchError(f"{host} took too long to send the page.") from None
    except requests.exceptions.SSLError:
        raise FetchError(f"The site's security certificate couldn't be verified, so I didn't connect.") from None
    except requests.exceptions.TooManyRedirects:
        raise FetchError("The site keeps redirecting in a loop.") from None
    except (requests.exceptions.InvalidURL, requests.exceptions.InvalidSchema,
            requests.exceptions.MissingSchema):
        raise FetchError("That doesn't look like a web address.") from None
    except requests.exceptions.ChunkedEncodingError:
        raise FetchError("The connection dropped while the page was downloading.") from None
    except requests.exceptions.ConnectionError as error:
        cause = error.args[0] if error.args else None
        if isinstance(cause, ReadTimeoutError) or isinstance(getattr(cause, "reason", None), ReadTimeoutError):
            raise FetchError(f"{host} took too long to send the page.") from None
        raise FetchError(f"Couldn't connect to {host}. Check the address and your Internet connection.") from None
    except requests.exceptions.RequestException as error:
        raise FetchError(f"Something went wrong while downloading the page: {error}") from None

if __name__ == "__main__":
    import sys
    
    for address in sys.argv[1:]:
        try:
            page = fetch(address)
            print("OK   ", page.url, f"({len(page.content)} bytes, {page.content_type or 'no content type'})")
        except FetchError as error:
            print("ERROR", error)
