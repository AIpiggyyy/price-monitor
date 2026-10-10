"""One monitoring pass: fetch each watched page, read price/stock, store it, decide on alerts."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .alerts import Alerter
from .config import Config, Watch
from .extract import extract
from .fetch import FetchError, Fetcher
from .store import Check, Store

log = logging.getLogger("monitor")


@dataclass
class Result:
    watch: str
    ok: bool
    price: float | None = None
    in_stock: bool | None = None
    alerts: list[str] | None = None
    error: str = ""


def money(w: Watch, v: float | None) -> str:
    return "n/a" if v is None else f"{w.currency}{v:,.2f}"


def evaluate(w: Watch, prev: Check | None, price: float | None, in_stock: bool | None, lowest_before: float | None) -> list[str]:
    """Pure function: which alerts should fire for this reading?"""
    out: list[str] = []
    if price is not None and w.target_price is not None and price <= w.target_price:
        if prev is None or prev.price is None or prev.price > w.target_price:  # only when it crosses
            out.append(f"🎯 {w.name} is {money(w, price)} - at or below your target {money(w, w.target_price)}")
    if price is not None and w.drop_pct and prev is not None and prev.price:
        change = price / prev.price - 1
        if change <= -w.drop_pct / 100:
            out.append(f"📉 {w.name} dropped {abs(change):.0%}: {money(w, prev.price)} → {money(w, price)}")
    if w.alert_restock and in_stock is True and prev is not None and prev.in_stock is False:
        out.append(f"📦 {w.name} is back in stock at {money(w, price)}")
    if price is not None and lowest_before is not None and price < lowest_before and not out:
        log.info("%s: new lowest price %s", w.name, money(w, price))
    return out


class Monitor:
    def __init__(self, cfg: Config, fetcher: Fetcher | None = None, store: Store | None = None, alerter: Alerter | None = None):
        s = cfg.settings
        self.cfg = cfg
        self.fetcher = fetcher or Fetcher(s.user_agent, s.timeout_s, s.retries, s.min_delay_per_domain_s, s.respect_robots_txt)
        self.store = store or Store(s.db_path)
        self.alerter = alerter or Alerter()

    def check(self, w: Watch) -> Result:
        prev = self.store.last_ok(w.name)
        lowest = self.store.lowest(w.name)
        try:
            html = self.fetcher.get(w.url)
            ex = extract(html, w.price_selector, w.stock_selector, w.out_of_stock_text)
            if ex.price is None and ex.in_stock is None:
                raise FetchError("couldn't find a price on the page - add price_selector for this site")
        except FetchError as e:
            self.store.add(Check(time.time(), w.name, None, None, False, str(e)))
            fails = self.store.failures_in_a_row(w.name)
            if fails == self.cfg.settings.alert_after_failures:
                self.alerter.send(f"⚠️ {w.name}: check failing", f"{fails} failed checks in a row. Last error: {e}\n{w.url}")
            log.warning("%s: %s", w.name, e)
            return Result(w.name, False, error=str(e))

        self.store.add(Check(time.time(), w.name, ex.price, ex.in_stock, True, method=ex.method))
        alerts = evaluate(w, prev, ex.price, ex.in_stock, lowest)
        for a in alerts:
            self.alerter.send(a, w.url)
        stock = {True: "in stock", False: "OUT OF STOCK", None: "stock unknown"}[ex.in_stock]
        log.info("%-28s %12s  %-13s via %s", w.name, money(w, ex.price), stock, ex.method)
        return Result(w.name, True, ex.price, ex.in_stock, alerts)

    def run_once(self) -> list[Result]:
        return [self.check(w) for w in self.cfg.watches]

    def run_forever(self) -> None:
        mins = self.cfg.settings.interval_minutes
        log.info("watching %d page(s) every %d min; alerts via %s", len(self.cfg.watches), mins, ", ".join(self.alerter.channels))
        while True:
            started = time.monotonic()
            try:
                self.run_once()
            except Exception:  # keep the loop alive; individual pages already handle their errors
                log.exception("pass failed")
            time.sleep(max(0, mins * 60 - (time.monotonic() - started)))
