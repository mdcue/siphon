# [NEW FILE] every line is new
"""Tests for siphon_app/core/polite.py. No internet and no real waiting: the session, the
clock and the waiting are all fakes."""
import threading

import pytest

from siphon_app import __url__
from siphon_app.core import fetcher, polite
from siphon_app.core.fetcher import FetchCancelled, FetchedPage, FetchError, make_session
from siphon_app.core.polite import PoliteFetcher, age_text, default_wait


class FakeResponse:
    def __init__(self, status=200, body=b"", boom=None):
        self.status_code, self.body, self.boom, self.closed = status, body, boom, False
        self.sent = 0                                  # how many bytes were actually asked for

    def iter_content(self, size):
        if self.boom:
            raise self.boom
        for i in range(0, len(self.body), size):
            self.sent += len(self.body[i:i + size])
            yield self.body[i:i + size]

    def close(self):
        self.closed = True


class FakeSession:
    """Answers robots.txt requests from a dictionary: {robots_url: FakeResponse or an Exception}."""
    def __init__(self, answers=None):
        self.answers, self.asked = answers or {}, []

    def get(self, url, **kwargs):
        self.asked.append(url)
        answer = self.answers.get(url, FakeResponse(404))
        if isinstance(answer, Exception):
            raise answer
        return answer


class Clock:
    def __init__(self):
        self.now, self.waits = 1000.0, []

    def __call__(self):
        return self.now

    def wait(self, seconds, event):
        self.waits.append(round(seconds, 3))
        self.now += seconds


def robots(text, status=200):
    return FakeResponse(status, text.encode())


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def downloads(monkeypatch):
    """Replace the real downloader with one that counts calls."""
    calls = []

    def fake(url, *, session=None, cancel_event=None, **kwargs):
        calls.append(url)
        return FetchedPage(url=url, content=b"<html>page</html>", content_type="text/html")

    monkeypatch.setattr(fetcher, "fetch", fake)
    return calls


def make(clock, answers=None):
    session = FakeSession(answers)
    return PoliteFetcher(session=session, clock=clock, wait=clock.wait), session


# ---- who we say we are -------------------------------------------------------------------

def test_the_user_agent_says_who_is_visiting_and_where_to_find_them():
    agent = make_session().headers["User-Agent"]
    assert "siphon/" in agent and __url__ in agent and __url__.startswith("https://github.com/")


def test_age_wording():
    assert age_text(0) == "0 seconds ago" and age_text(1) == "1 second ago" and age_text(59) == "59 seconds ago"
    assert age_text(60) == "1 minute ago" and age_text(125) == "2 minutes ago"


# ---- robots.txt --------------------------------------------------------------------------

def test_a_site_with_no_robots_file_is_fine(clock, downloads):
    pf, session = make(clock)
    page = pf.fetch("https://example.com/data")
    assert page.content == b"<html>page</html>" and downloads == ["https://example.com/data"]
    assert session.asked == ["https://example.com/robots.txt"]


def test_a_disallowed_page_is_refused_with_a_friendly_message_and_never_downloaded(clock, downloads):
    pf, _ = make(clock, {"https://example.com/robots.txt": robots("User-agent: *\nDisallow: /private")})
    with pytest.raises(FetchError) as caught:
        pf.fetch("https://example.com/private/list")
    assert "example.com" in str(caught.value) and "robots.txt" in str(caught.value)
    assert "Open file" in str(caught.value) and downloads == []


def test_other_pages_on_the_same_site_are_still_allowed(clock, downloads):
    pf, _ = make(clock, {"https://example.com/robots.txt": robots("User-agent: *\nDisallow: /private")})
    pf.fetch("https://example.com/public")
    assert downloads == ["https://example.com/public"]


def test_a_rule_aimed_at_siphon_by_name_applies(clock, downloads):
    pf, _ = make(clock, {"https://example.com/robots.txt": robots("User-agent: siphon\nDisallow: /")})
    with pytest.raises(FetchError):
        pf.fetch("https://example.com/anything")


def test_a_rule_aimed_at_another_robot_does_not_apply(clock, downloads):
    pf, _ = make(clock, {"https://example.com/robots.txt": robots("User-agent: otherbot\nDisallow: /")})
    pf.fetch("https://example.com/anything")
    assert downloads


def test_a_site_that_blocks_everything_blocks_us(clock, downloads):
    pf, _ = make(clock, {"https://example.com/robots.txt": robots("User-agent: *\nDisallow: /")})
    with pytest.raises(FetchError):
        pf.fetch("https://example.com/")


def test_rules_are_remembered_so_robots_txt_is_asked_for_only_once(clock, downloads):
    pf, session = make(clock)
    pf.fetch("https://example.com/a")
    pf.fetch("https://example.com/b")
    assert session.asked == ["https://example.com/robots.txt"]


def test_rules_are_asked_for_again_after_an_hour(clock, downloads):
    pf, session = make(clock)
    pf.fetch("https://example.com/a")
    clock.now += polite.ROBOTS_TTL + 1
    pf.fetch("https://example.com/b")
    assert len(session.asked) == 2


def test_rules_are_still_remembered_just_before_the_hour_is_up(clock, downloads):
    pf, session = make(clock)
    pf.fetch("https://example.com/a")
    clock.now += polite.ROBOTS_TTL - 1
    pf.fetch("https://example.com/b")
    assert len(session.asked) == 1


def test_every_site_has_its_own_rules(clock, downloads):
    pf, session = make(clock, {"https://blocked.com/robots.txt": robots("User-agent: *\nDisallow: /")})
    pf.fetch("https://open.com/x")
    with pytest.raises(FetchError):
        pf.fetch("https://blocked.com/x")
    assert sorted(session.asked) == ["https://blocked.com/robots.txt", "https://open.com/robots.txt"]


def test_the_port_is_kept_when_asking_for_robots_txt(clock, downloads):
    pf, session = make(clock)
    pf.fetch("http://localhost:8000/page")
    assert session.asked == ["http://localhost:8000/robots.txt"]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410])
def test_a_missing_or_forbidden_robots_file_means_everything_is_allowed(clock, downloads, status):
    pf, session = make(clock, {"https://example.com/robots.txt": FakeResponse(status, b"User-agent: *\nDisallow: /")})
    pf.fetch("https://example.com/a")
    pf.fetch("https://example.com/b")
    assert len(downloads) == 2 and len(session.asked) == 1          # and that answer is remembered


@pytest.mark.parametrize("trouble", [FakeResponse(500), FakeResponse(503),
                                     ConnectionError("down"), TimeoutError("slow"),
                                     FakeResponse(200, b"x", boom=OSError("cut off"))])
def test_trouble_getting_robots_txt_does_not_stop_the_page_and_is_not_remembered(clock, downloads, trouble):
    pf, session = make(clock, {"https://example.com/robots.txt": trouble})
    pf.fetch("https://example.com/a")
    pf.fetch("https://example.com/b")
    assert len(downloads) == 2 and len(session.asked) == 2          # asked again the second time


def test_a_garbage_robots_file_is_harmless(clock, downloads):
    pf, _ = make(clock, {"https://example.com/robots.txt": FakeResponse(200, b"\xff\xfe\x00 not text \x80")})
    pf.fetch("https://example.com/a")
    assert downloads


def test_a_huge_robots_file_is_only_read_up_to_the_limit(clock, downloads):
    pf, _ = make(clock, {"https://example.com/robots.txt": robots("User-agent: *\nDisallow: /late\n" + "#" * 2_000_000)})
    pf.fetch("https://example.com/early")
    assert downloads                                                  # did not hang or crash


def test_reading_stops_at_the_limit_instead_of_downloading_everything(clock, downloads):
    response = robots("User-agent: *\nAllow: /\n" + "#" * 2_000_000)
    pf, _ = make(clock, {"https://example.com/robots.txt": response})
    pf.fetch("https://example.com/a")
    assert polite.ROBOTS_MAX_BYTES <= response.sent < polite.ROBOTS_MAX_BYTES + 8192


def test_rules_after_the_size_limit_are_ignored(clock, downloads):
    filler = "# filler\n" * (polite.ROBOTS_MAX_BYTES // 9 + 10)
    pf, _ = make(clock, {"https://example.com/robots.txt": robots(filler + "User-agent: *\nDisallow: /")})
    pf.fetch("https://example.com/a")
    assert downloads


def test_the_robots_response_is_always_closed(clock, downloads):
    response = robots("User-agent: *\nAllow: /")
    pf, _ = make(clock, {"https://example.com/robots.txt": response})
    pf.fetch("https://example.com/a")
    assert response.closed


# ---- the pause between requests ----------------------------------------------------------

def test_the_first_visit_to_a_site_does_not_wait(clock, downloads):
    pf, _ = make(clock)
    pf.fetch("https://example.com/a")
    assert clock.waits == []


def test_a_second_page_from_the_same_site_waits_the_minimum_delay(clock, downloads):
    pf, _ = make(clock)
    pf.fetch("https://example.com/a")
    pf.fetch("https://example.com/b")
    assert clock.waits == [polite.MIN_DELAY]


def test_no_wait_is_needed_once_enough_time_has_passed(clock, downloads):
    pf, _ = make(clock)
    pf.fetch("https://example.com/a")
    clock.now += polite.MIN_DELAY + 0.5
    pf.fetch("https://example.com/b")
    assert clock.waits == []


def test_only_the_remaining_time_is_waited(clock, downloads):
    pf, _ = make(clock)
    pf.fetch("https://example.com/a")
    clock.now += 0.4
    pf.fetch("https://example.com/b")
    assert clock.waits == [pytest.approx(polite.MIN_DELAY - 0.4)]


def test_even_a_short_remaining_wait_is_honoured(clock, downloads):
    pf, _ = make(clock)
    pf.fetch("https://example.com/a")
    clock.now += polite.MIN_DELAY - 0.2
    pf.fetch("https://example.com/b")
    assert clock.waits == [pytest.approx(0.2)]


def test_different_sites_never_wait_for_each_other(clock, downloads):
    pf, _ = make(clock)
    pf.fetch("https://one.com/a")
    pf.fetch("https://two.com/a")
    assert clock.waits == []


def test_a_crawl_delay_in_robots_txt_is_obeyed(clock, downloads):
    pf, _ = make(clock, {"https://example.com/robots.txt": robots("User-agent: *\nCrawl-delay: 4")})
    pf.fetch("https://example.com/a")
    pf.fetch("https://example.com/b")
    assert clock.waits == [4.0]


def test_a_crawl_delay_is_capped(clock, downloads):
    pf, _ = make(clock, {"https://example.com/robots.txt": robots("User-agent: *\nCrawl-delay: 600")})
    pf.fetch("https://example.com/a")
    pf.fetch("https://example.com/b")
    assert clock.waits == [polite.MAX_DELAY]


def test_a_tiny_crawl_delay_never_goes_below_the_minimum(clock, downloads):
    pf, _ = make(clock, {"https://example.com/robots.txt": robots("User-agent: *\nCrawl-delay: 0")})
    pf.fetch("https://example.com/a")
    pf.fetch("https://example.com/b")
    assert clock.waits == [polite.MIN_DELAY]


def test_time_slots_are_handed_out_one_after_another(clock):
    """Two jobs at the same moment (a cancelled one still running) must not both go at once."""
    pf, _ = make(clock)
    assert pf._reserve("example.com", 2.0) == 0
    assert pf._reserve("example.com", 2.0) == 2.0
    assert pf._reserve("example.com", 2.0) == 4.0
    assert pf._reserve("other.com", 2.0) == 0


def test_waiting_can_be_cancelled_at_once():
    event = threading.Event()
    event.set()
    with pytest.raises(FetchCancelled):
        default_wait(30, event)


def test_waiting_without_a_cancel_flag_just_sleeps(monkeypatch):
    slept = []
    monkeypatch.setattr(polite.time, "sleep", slept.append)
    default_wait(2.5, None)
    assert slept == [2.5]


def test_waiting_ends_normally_when_nobody_cancels():
    default_wait(0.01, threading.Event())


def test_cancelling_during_the_pause_stops_the_fetch_before_any_download(clock, downloads):
    pf = PoliteFetcher(session=FakeSession(), clock=clock,
                       wait=lambda seconds, event: (_ for _ in ()).throw(FetchCancelled("Cancelled.")))
    pf.fetch("https://example.com/a")                                # first one: no wait
    with pytest.raises(FetchCancelled):
        pf.fetch("https://example.com/b")
    assert downloads == ["https://example.com/a"]


# ---- the memory of recent pages ----------------------------------------------------------

def test_the_same_page_twice_downloads_once(clock, downloads):
    pf, _ = make(clock)
    first = pf.fetch("https://example.com/a")
    clock.now += 40
    second = pf.fetch("https://example.com/a")
    assert downloads == ["https://example.com/a"]
    assert second.content == first.content
    assert first.note == "" and "40 seconds ago" in second.note and "Ctrl+R" in second.note


def test_the_remembered_copy_expires(clock, downloads):
    pf, _ = make(clock)
    pf.fetch("https://example.com/a")
    clock.now += polite.CACHE_TTL + 1
    page = pf.fetch("https://example.com/a")
    assert len(downloads) == 2 and page.note == ""


def test_the_remembered_copy_expires_at_exactly_the_limit(clock, downloads):
    pf, _ = make(clock)
    pf.fetch("https://example.com/a")
    clock.now += polite.CACHE_TTL
    pf.fetch("https://example.com/a")
    assert len(downloads) == 2


def test_the_remembered_copy_is_still_used_just_before_it_expires(clock, downloads):
    pf, _ = make(clock)
    pf.fetch("https://example.com/a")
    clock.now += polite.CACHE_TTL - 1
    pf.fetch("https://example.com/a")
    assert len(downloads) == 1


def test_a_remembered_page_does_not_touch_the_site_at_all(clock, downloads):
    pf, session = make(clock)
    pf.fetch("https://example.com/a")
    before = (len(session.asked), list(clock.waits))
    pf.fetch("https://example.com/a")
    assert (len(session.asked), clock.waits) == before


def test_forget_makes_the_next_fetch_go_to_the_site(clock, downloads):
    pf, _ = make(clock)
    pf.fetch("https://example.com/a")
    pf.forget("https://example.com/a")
    pf.fetch("https://example.com/a")
    assert len(downloads) == 2


def test_forgetting_works_even_for_a_loosely_typed_address(clock, downloads):
    pf, _ = make(clock)
    pf.fetch("example.com/a")
    pf.forget("  example.com/a ")
    pf.fetch("https://example.com/a")
    assert len(downloads) == 2


def test_forgetting_a_bad_address_or_an_unknown_one_is_harmless(clock):
    pf, _ = make(clock)
    pf.forget("mailto:me@example.com")
    pf.forget("https://never-seen.com/")


def test_a_loosely_typed_address_shares_the_same_remembered_copy(clock, downloads):
    pf, _ = make(clock)
    pf.fetch("example.com/a")
    pf.fetch("https://example.com/a")
    assert len(downloads) == 1


def test_different_pages_are_remembered_separately(clock, downloads):
    pf, _ = make(clock)
    pf.fetch("https://example.com/a")
    clock.now += 5
    pf.fetch("https://example.com/b")
    assert len(downloads) == 2


def test_a_failed_download_is_not_remembered(clock, monkeypatch):
    attempts = []

    def failing(url, *, session=None, cancel_event=None, **kwargs):
        attempts.append(url)
        raise FetchError("nope")

    monkeypatch.setattr(fetcher, "fetch", failing)
    pf, _ = make(clock)
    for _ in range(2):
        clock.now += 5
        with pytest.raises(FetchError):
            pf.fetch("https://example.com/a")
    assert len(attempts) == 2


def test_a_refused_page_is_not_remembered_and_is_refused_again(clock, downloads):
    pf, _ = make(clock, {"https://example.com/robots.txt": robots("User-agent: *\nDisallow: /")})
    for _ in range(2):
        with pytest.raises(FetchError):
            pf.fetch("https://example.com/a")


def test_only_a_few_pages_are_remembered_and_the_oldest_goes_first(clock, downloads):
    pf, _ = make(clock)
    for i in range(polite.CACHE_MAX_PAGES + 1):
        clock.now += 2
        pf.fetch(f"https://example.com/{i}")
    assert len(pf._pages) == polite.CACHE_MAX_PAGES
    count = len(downloads)
    pf.fetch(f"https://example.com/{polite.CACHE_MAX_PAGES}")        # the newest: still remembered
    assert len(downloads) == count
    pf.fetch("https://example.com/0")                                # the oldest: gone
    assert len(downloads) == count + 1


def test_remembering_a_page_again_makes_it_the_newest(clock):
    pf, _ = make(clock)
    page = FetchedPage(url="x", content=b"", content_type="")
    pf._remember("https://e.com/0", page)
    pf._remember("https://e.com/1", page)
    pf._remember("https://e.com/0", page)                          # seen again: now the newest
    for i in range(2, polite.CACHE_MAX_PAGES + 1):
        pf._remember(f"https://e.com/{i}", page)
    assert "https://e.com/0" in pf._pages and "https://e.com/1" not in pf._pages


def test_a_very_big_page_is_not_remembered(clock, monkeypatch):
    calls = []

    def big(url, *, session=None, cancel_event=None, **kwargs):
        calls.append(url)
        return FetchedPage(url=url, content=b"x" * (polite.CACHE_MAX_BYTES + 1), content_type="text/html")

    monkeypatch.setattr(fetcher, "fetch", big)
    pf, _ = make(clock)
    pf.fetch("https://example.com/a")
    clock.now += 5
    pf.fetch("https://example.com/a")
    assert len(calls) == 2


def test_a_page_exactly_at_the_size_limit_is_remembered(clock, monkeypatch):
    calls = []

    def exact(url, *, session=None, cancel_event=None, **kwargs):
        calls.append(url)
        return FetchedPage(url=url, content=b"x" * polite.CACHE_MAX_BYTES, content_type="text/html")

    monkeypatch.setattr(fetcher, "fetch", exact)
    pf, _ = make(clock)
    pf.fetch("https://example.com/a")
    pf.fetch("https://example.com/a")
    assert len(calls) == 1


def test_a_bad_address_is_reported_before_anything_else(clock, downloads):
    pf, session = make(clock)
    with pytest.raises(FetchError, match="http and https"):
        pf.fetch("mailto:me@example.com")
    assert session.asked == [] and downloads == []


def test_the_downloader_is_given_the_shared_session_and_the_cancel_flag(clock, monkeypatch):
    seen = {}

    def spy(url, *, session=None, cancel_event=None, **kwargs):
        seen.update(session=session, cancel_event=cancel_event)
        return FetchedPage(url=url, content=b"", content_type="")

    monkeypatch.setattr(fetcher, "fetch", spy)
    pf, session = make(clock)
    event = threading.Event()
    pf.fetch("https://example.com/a", cancel_event=event)
    assert seen["session"] is session and seen["cancel_event"] is event


# ---- the shared one used by the window ---------------------------------------------------

def test_the_module_level_functions_use_one_shared_fetcher(monkeypatch, clock, downloads):
    shared, _ = make(clock)
    monkeypatch.setattr(polite, "_default", shared)
    polite.polite_fetch("https://example.com/a")
    polite.polite_fetch("https://example.com/a")
    assert len(downloads) == 1
    polite.forget("https://example.com/a")
    polite.polite_fetch("https://example.com/a")
    assert len(downloads) == 2


def test_the_shared_fetcher_is_created_once(monkeypatch):
    monkeypatch.setattr(polite, "_default", None)
    first = polite._shared()
    assert polite._shared() is first
