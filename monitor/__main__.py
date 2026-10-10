"""Command line.

    python -m monitor demo                                  # offline demo with a fake shop
    python -m monitor test-url https://shop.example/item    # what can we read from this page?
    python -m monitor check --config watches.toml           # one pass now
    python -m monitor run   --config watches.toml           # keep checking every interval
    python -m monitor history --config watches.toml
    python -m monitor export --config watches.toml --out prices.csv
    python -m monitor chart  --config watches.toml --out prices.png
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from .config import Settings, load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="monitor")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "run", "history", "export", "chart"):
        s = sub.add_parser(name)
        s.add_argument("--config", default="watches.toml")
        if name in ("export", "chart"):
            s.add_argument("--out", required=True)
    t = sub.add_parser("test-url", help="show what the monitor can read from a page")
    t.add_argument("url")
    t.add_argument("--price-selector")
    t.add_argument("--stock-selector")
    d = sub.add_parser("demo", help="offline demo against a local fake shop")
    d.add_argument("--chart", default="demo_prices.png")
    a = p.parse_args(argv)

    if a.cmd == "demo":
        from .demo import run_demo

        logging.getLogger().setLevel(logging.WARNING)
        mon = run_demo(chart=a.chart)
        print(f"\n{len(mon.alerter.sent)} alerts sent. Price chart saved to {a.chart}")
        return

    if a.cmd == "test-url":
        from .extract import extract
        from .fetch import FetchError, Fetcher

        s = Settings()
        try:
            html = Fetcher(s.user_agent, s.timeout_s, 1, 0, s.respect_robots_txt).get(a.url)
        except FetchError as e:
            sys.exit(f"Couldn't fetch: {e}")
        ex = extract(html, a.price_selector, a.stock_selector)
        print(f"title:    {ex.title}\nprice:    {ex.price} {ex.currency or ''}\nin stock: {ex.in_stock}\nmethod:   {ex.method}")
        if ex.price is None:
            print("\nNo price found. Open the page, right-click the price > Inspect, and pass a CSS selector, "
                  "e.g. --price-selector 'span.price'. Pages that build prices with JavaScript need a browser-based fetcher.")
        return

    from .core import Monitor
    from .report import chart, export_csv

    cfg = load_config(a.config)
    mon = Monitor(cfg)
    if a.cmd == "check":
        mon.run_once()
    elif a.cmd == "run":
        mon.run_forever()
    elif a.cmd == "history":
        for c in mon.store.history():
            when = datetime.fromtimestamp(c.ts, timezone.utc).strftime("%Y-%m-%d %H:%M")
            print(f"{when}  {c.watch:28} {'' if c.price is None else f'{c.price:,.2f}':>10}  "
                  f"{'' if c.in_stock is None else ('in stock' if c.in_stock else 'out of stock'):12} {c.error}")
    elif a.cmd == "export":
        n = export_csv(mon.store, a.out)
        print(f"Wrote {n} rows to {a.out}")
    elif a.cmd == "chart":
        chart(mon.store, [w.name for w in cfg.watches], a.out,
              targets={w.name: w.target_price for w in cfg.watches if w.target_price})
        print(f"Saved {a.out}")


if __name__ == "__main__":
    main()
