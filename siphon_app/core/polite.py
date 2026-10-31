# [NEW FILE] every line is new
"""
siphon_app/core/polite.py

Good manners for a program that visits other people's websites:

  * robots.txt: a site can publish rules saying which pages robots may read. We obey them.
  * a pause between requests to the same site, so we never hammer it.
  * a short memory of recent pages, so pressing Fetch twice does not download twice.

The address of the project is sent in the User-Agent (see fetcher.make_session), so a site's
owner can see who is visiting and get in touch. Nothing here knows about windows or buttons.
"""
import threading
import time
from dataclasses import replace
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from siphon_app.core import fetcher
from siphon_app.core.fetcher import FetchCancelled, FetchedPage, FetchError, normalize_url

ROBOT_NAME = "siphon"           # the name a robots.txt file uses to talk to us
MIN_DELAY = 1.0                 # seconds between two requests to the same site
MAX_DELAY = 10.0                # the longest pause we will accept, even if a site asks for more
ROBOTS_TTL = 3600               # seconds a site's rules are remembered (1 hour)
ROBOTS_MAX_BYTES = 512 * 1024   # the most of a robots.txt we will read
ROBOTS_TIMEOUT = (5, 10)        # (connect, read) seconds, like the page downloads
CACHE_TTL = 300                 # seconds a downloaded page is remembered (5 minutes)
CACHE_MAX_PAGES = 10            # how many pages are remembered at once
CACHE_MAX_BYTES = 5 * 1024 * 1024    # bigger pages are not remembered (keeps memory small)


def default_wait(seconds: float, cancel_event: threading.Event | None) -> None:
    """Sleep, but wake up at once (and raise) if the person presses Cancel."""
    if cancel_event is None:
        time.sleep(seconds)
    elif cancel_event.wait(seconds):
        raise FetchCancelled("Cancelled.")


def age_text(seconds: float) -> str:
    """'40 seconds ago', '1 minute ago', '3 minutes ago'."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''} ago"
    minutes = seconds // 60
    return f"{minutes} minute{'s' if minutes != 1 else ''} ago"


class PoliteFetcher:
    def __init__(self, session=None, clock=time.monotonic, wait=default_wait) -> None:
        self.session = session or fetcher.make_session()
        self._clock = clock                           # tests swap these two for fakes,
        self._wait = wait                             # so no test ever really sleeps
        self._lock = threading.Lock()                 # a cancelled job's thread may still be running
        self._robots: dict[str, tuple[float, RobotFileParser | None]] = {}   # host -> (when, rules)
        self._next_slot: dict[str, float] = {}        # host -> earliest time of its next request
        self._pages: dict[str, tuple[float, FetchedPage]] = {}               # address -> (when, page)

    # ---- the public part -------------------------------------------------------------

    def fetch(self, url: str, cancel_event: threading.Event | None = None) -> FetchedPage:
        """Like fetcher.fetch, but polite. Raises FetchError (or FetchCancelled)."""
        url = normalize_url(url)
        cached = self._cached(url)
        if cached is not None:
            return cached
        host = urlparse(url).hostname or ""
        rules = self._rules_for(url, host, cancel_event)
        if rules is not None and not rules.can_fetch(ROBOT_NAME, url):
            raise FetchError(
                f"{host} asks robots not to read this page (robots.txt), so siphon didn't fetch it. "
                "If you can open it in your browser, save the page and use Open file... instead.")
        self._pause(host, self._delay(rules), cancel_event)
        page = fetcher.fetch(url, session=self.session, cancel_event=cancel_event)
        self._remember(url, page)
        return page

    def forget(self, url: str) -> None:
        """Drop the remembered copy of a page, so the next fetch goes to the site."""
        try:
            url = normalize_url(url)
        except FetchError:
            return
        with self._lock:
            self._pages.pop(url, None)

    # ---- the pause between requests --------------------------------------------------

    def _delay(self, rules: RobotFileParser | None) -> float:
        asked = rules.crawl_delay(ROBOT_NAME) if rules is not None else None
        if asked is None:
            return MIN_DELAY
        return min(max(float(asked), MIN_DELAY), MAX_DELAY)

    def _reserve(self, host: str, delay: float) -> float:
        """Book the next free time slot for this site; return how long to wait for it."""
        with self._lock:
            now = self._clock()
            slot = max(now, self._next_slot.get(host, now))
            self._next_slot[host] = slot + delay
            return slot - now

    def _pause(self, host: str, delay: float, cancel_event) -> None:
        wait = self._reserve(host, delay)
        if wait > 0:
            self._wait(wait, cancel_event)

    # ---- robots.txt ------------------------------------------------------------------

    def _rules_for(self, url: str, host: str, cancel_event) -> RobotFileParser | None:
        """The site's robots.txt rules, or None when there are none (or we couldn't get them)."""
        with self._lock:
            known = self._robots.get(host)
        if known is not None and self._clock() - known[0] < ROBOTS_TTL:
            return known[1]
        scheme = urlparse(url).scheme
        port = urlparse(url).port
        origin = f"{scheme}://{host}" + (f":{port}" if port else "")
        self._pause(host, 0, cancel_event)               # a tiny file: no pause after it, but never two at once
        rules, trustworthy = self._download_rules(f"{origin}/robots.txt")
        if trustworthy:                                  # a hiccup is not remembered: ask again next time
            with self._lock:
                self._robots[host] = (self._clock(), rules)
        return rules

    def _download_rules(self, robots_url: str) -> tuple[RobotFileParser | None, bool]:
        """Returns (rules or None, whether the answer is worth remembering)."""
        try:
            response = self.session.get(robots_url, stream=True, timeout=ROBOTS_TIMEOUT)
        except Exception:                                # any network trouble: the page download will explain it
            return None, False
        try:
            if response.status_code >= 500:
                return None, False                       # the site is struggling; don't remember that
            if response.status_code >= 400:
                return None, True                        # no robots.txt (or not for us): everything is allowed
            data = bytearray()
            for chunk in response.iter_content(8192):
                data.extend(chunk)
                if len(data) >= ROBOTS_MAX_BYTES:
                    break
            lines = bytes(data[:ROBOTS_MAX_BYTES]).decode("utf-8", errors="replace").splitlines()
        except Exception:
            return None, False
        finally:
            response.close()
        rules = RobotFileParser()
        rules.parse(lines)
        return rules, True

    # ---- the memory of recent pages --------------------------------------------------

    def _cached(self, url: str) -> FetchedPage | None:
        with self._lock:
            entry = self._pages.get(url)
            if entry is None:
                return None
            age = self._clock() - entry[0]
            if age >= CACHE_TTL:
                del self._pages[url]
                return None
            return replace(entry[1], note=f"Used the copy from {age_text(age)}; the site wasn't contacted. "
                                          "Press Ctrl+R to download it again.")

    def _remember(self, url: str, page: FetchedPage) -> None:
        if len(page.content) > CACHE_MAX_BYTES:
            return
        with self._lock:
            self._pages.pop(url, None)
            self._pages[url] = (self._clock(), page)
            while len(self._pages) > CACHE_MAX_PAGES:
                del self._pages[next(iter(self._pages))]       # the oldest goes first


# ---- one shared fetcher for the whole program -------------------------------------------

_default: PoliteFetcher | None = None
_default_lock = threading.Lock()


def _shared() -> PoliteFetcher:
    global _default
    with _default_lock:
        if _default is None:
            _default = PoliteFetcher()
        return _default


def polite_fetch(url: str, cancel_event: threading.Event | None = None) -> FetchedPage:
    """The function the window calls. Same shape as fetcher.fetch, with good manners."""
    return _shared().fetch(url, cancel_event=cancel_event)


def forget(url: str) -> None:
    _shared().forget(url)
