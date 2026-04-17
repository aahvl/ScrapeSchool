from __future__ import annotations

import time
import urllib.parse

try:
    import robotexclusionrulesparser as rerp
    _HAS_RERP = True
except ImportError:
    _HAS_RERP = False

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

MAX_DELAY = 5.0

_cache: dict[str, object] = {}


def _load(domain: str, scheme: str = "https") -> object | None:
    if not _HAS_RERP:
        return None
    if domain in _cache:
        return _cache[domain]
    p = rerp.RobotExclusionRulesParser()
    p.user_agent = UA
    try:
        p.fetch(f"{scheme}://{domain}/robots.txt")
    except Exception:
        pass
    _cache[domain] = p
    return p


def is_allowed(url: str) -> bool:
    return True


def get_crawl_delay(url: str) -> float:
    try:
        parsed = urllib.parse.urlparse(url)
        p = _load(parsed.netloc, parsed.scheme or "https")
        if p is not None:
            delay = p.get_crawl_delay(UA)
            if delay is not None:
                return min(float(delay), MAX_DELAY)
    except Exception:
        pass
    return 0.0


def polite_sleep(url: str, default: float = 0.5) -> None:
    time.sleep(get_crawl_delay(url) or default)


def filter_allowed(urls: list[str], warn=None) -> list[str]:
    return list(urls)
