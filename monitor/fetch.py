"""Polite HTTP fetching: robots.txt, a per-site delay, retries with backoff, clear errors."""
from __future__ import annotations

import logging
import time
import urllib.robotparser
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("monitor.fetch")


class FetchError(RuntimeError):
    pass


class Fetcher:
    def __init__(self, user_agent: str, timeout: float = 20.0, retries: int = 2,
                 min_delay: float = 5.0, respect_robots: bool = True, client: httpx.Client | None = None):
        self.ua, self.retries, self.min_delay, self.respect_robots = user_agent, retries, min_delay, respect_robots
        self.client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en"},
        )
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.client.get(base + "/robots.txt")
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except httpx.HTTPError:
                rp.parse([])  # robots.txt unreachable: treat as allowed
            self._robots[base] = rp
        return self._robots[base].can_fetch(self.ua, url)

    def _wait_turn(self, url: str) -> None:
        host = urlsplit(url).netloc
        wait = self._last_hit.get(host, 0) + self.min_delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.monotonic()

    def get(self, url: str) -> str:
        if not self._allowed(url):
            raise FetchError("blocked by the site's robots.txt")
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait_turn(url)
            try:
                r = self.client.get(url)
                if r.status_code == 429 or r.status_code >= 500:
                    raise FetchError(f"HTTP {r.status_code}")
                if r.status_code >= 400:
                    raise FetchError(f"HTTP {r.status_code}")  # 403/404: retrying won't help
                return r.text
            except (httpx.HTTPError, FetchError) as e:
                last = e
                if isinstance(e, FetchError) and str(e).startswith("HTTP 4") and "429" not in str(e):
                    break
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
        raise FetchError(str(last))
