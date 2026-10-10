"""Offline demo: a tiny local web shop whose prices and stock change between checks,
so you can watch the monitor detect drops, targets and restocks without touching real sites."""
from __future__ import annotations

import json
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .alerts import Alerter
from .config import Config, Settings, Watch
from .core import Monitor
from .fetch import Fetcher
from .store import Store

# Three fictional products, published three different ways (like real shops do).
# Each list is the (price, in_stock) on successive "days".
TIMELINE = {
    "headphones": [(249.0, True), (249.0, True), (229.0, True), (199.0, True), (199.0, True), (179.0, True)],
    "grinder": [(389.0, True), (389.0, False), (389.0, False), (349.0, True), (349.0, True), (329.0, True)],
    "desk": [(699.0, True), (699.0, True), (649.0, True), (649.0, True), (549.0, True), (549.0, True)],
}

PAGES = {
    # JSON-LD structured data (Shopify, WooCommerce, most big retailers)
    "headphones": lambda p, s: f"""<html><head><title>Aurora ANC Headphones | Example Audio</title>
<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", "@type": "Product", "name": "Aurora ANC Headphones",
    "offers": {"@type": "Offer", "price": f"{p:.2f}", "priceCurrency": "AUD",
               "availability": "https://schema.org/" + ("InStock" if s else "OutOfStock")}})}</script>
</head><body><h1>Aurora ANC Headphones</h1><p class="price">A${p:,.2f}</p></body></html>""",
    # Open Graph product meta tags
    "grinder": lambda p, s: f"""<html><head><title>Conical Burr Grinder</title>
<meta property="og:title" content="Conical Burr Grinder">
<meta property="product:price:amount" content="{p:.2f}">
<meta property="product:price:currency" content="AUD">
<meta property="product:availability" content="{'in stock' if s else 'out of stock'}">
</head><body><h1>Conical Burr Grinder</h1></body></html>""",
    # No structured data at all: needs a CSS selector
    "desk": lambda p, s: f"""<html><head><title>Oak Standing Desk - Example Furniture</title></head><body>
<div class="product"><h1>Oak Standing Desk</h1><span class="amount">$ {p:,.2f}</span>
<div id="stock">{'In stock, ships in 2 days' if s else 'Out of stock'}</div></div></body></html>""",
}

WATCHES = [
    Watch(name="Aurora ANC Headphones", url="/p/headphones", target_price=200, currency="A$"),
    Watch(name="Conical Burr Grinder", url="/p/grinder", drop_pct=5, currency="A$"),
    Watch(name="Oak Standing Desk", url="/p/desk", price_selector="span.amount", stock_selector="#stock",
          drop_pct=10, target_price=600, currency="A$"),
]


def _server(state: dict) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            slug = self.path.rsplit("/", 1)[-1]
            if self.path == "/robots.txt":
                body, code = "User-agent: *\nAllow: /\n", 200
            elif slug in PAGES:
                price, stock = TIMELINE[slug][state["day"]]
                body, code = PAGES[slug](price, stock), 200
            else:
                body, code = "not found", 404
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *a):
            pass

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def run_demo(db_path: str | None = None, chart: str | None = None, quiet: bool = False) -> Monitor:
    state = {"day": 0}
    srv = _server(state)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    db = db_path or str(Path(tempfile.mkdtemp()) / "demo.sqlite")
    watches = [Watch(**{**w.__dict__, "url": base + w.url}) for w in WATCHES]
    cfg = Config(Settings(db_path=db, min_delay_per_domain_s=0, retries=0), watches)
    mon = Monitor(cfg, Fetcher(cfg.settings.user_agent, 5, 0, 0), Store(db), Alerter(env={}))
    store = mon.store
    try:
        for day in range(len(TIMELINE["desk"])):
            state["day"] = day
            if not quiet:
                print(f"\n=== Check {day + 1} ===")
            for w in watches:
                r = mon.check(w)
                # spread the demo checks over fake days so the chart has a time axis
                with store._db() as conn:
                    conn.execute("UPDATE checks SET ts=? WHERE rowid=(SELECT MAX(rowid) FROM checks)", (time.time() - (6 - day) * 86400,))
                if not quiet:
                    stock = {True: "in stock", False: "OUT OF STOCK", None: "?"}[r.in_stock]
                    print(f"  {w.name:24} {w.currency}{r.price:>8,.2f}  {stock}")
    finally:
        srv.shutdown()
    if chart:
        from .report import chart as make_chart

        make_chart(store, [w.name for w in watches], chart, currency="A$",
                   targets={w.name: w.target_price for w in watches if w.target_price})
    return mon
