import json

import httpx
import pytest

from monitor.alerts import Alerter
from monitor.config import Config, Settings, Watch, load_config
from monitor.core import Monitor, evaluate
from monitor.demo import run_demo
from monitor.extract import extract, parse_price
from monitor.fetch import FetchError, Fetcher
from monitor.store import Check, Store


# ---- price parsing ----------------------------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("$1,299.00", 1299.0),
        ("1.299,00 €", 1299.0),
        ("A$49", 49.0),
        ("From $10.50", 10.5),
        ("12,5", 12.5),
        ("1,299", 1299.0),
        ("$ 2 499", 2499.0),
        ("1.299.000", 1299000.0),
        (199, 199.0),
        ("Call for price", None),
    ],
)
def test_parse_price(text, expected):
    assert parse_price(text) == expected


# ---- extraction --------------------------------------------------------------------
def page_jsonld(data):
    return f'<html><head><title>T</title><script type="application/ld+json">{json.dumps(data)}</script></head><body></body></html>'


def test_jsonld_product_offer():
    html = page_jsonld({"@type": "Product", "name": "Kettle",
                        "offers": {"@type": "Offer", "price": "89.95", "priceCurrency": "AUD",
                                   "availability": "https://schema.org/OutOfStock"}})
    ex = extract(html)
    assert (ex.price, ex.in_stock, ex.currency, ex.method, ex.title) == (89.95, False, "AUD", "json-ld", "Kettle")


def test_jsonld_graph_and_aggregate_offer():
    html = page_jsonld({"@graph": [{"@type": "WebPage"},
                                   {"@type": "Product", "offers": {"@type": "AggregateOffer", "lowPrice": 15, "highPrice": 30}}]})
    assert extract(html).price == 15.0


def test_meta_tags():
    html = ('<html><head><meta property="product:price:amount" content="1299.00">'
            '<meta property="product:availability" content="in stock"></head></html>')
    ex = extract(html)
    assert (ex.price, ex.in_stock, ex.method) == (1299.0, True, "meta")


def test_css_selector_and_stock_text():
    html = '<div><span class="amount">$ 649.00</span><div id="stock">Sold out - Out of stock</div></div>'
    ex = extract(html, "span.amount", "#stock")
    assert (ex.price, ex.in_stock, ex.method) == (649.0, False, "css")


def test_broken_jsonld_falls_back_to_meta():
    html = ('<script type="application/ld+json">{not json</script>'
            '<meta property="og:price:amount" content="10">')
    assert extract(html).price == 10.0


def test_nothing_found():
    assert extract("<html><body>hello</body></html>").method == "none"


# ---- alert rules ------------------------------------------------------------------
def prev(price, stock=True):
    return Check(0, "w", price, stock, True)


def test_target_alert_fires_once_when_crossed():
    w = Watch("Desk", "https://x", target_price=600)
    assert evaluate(w, prev(649), 599, True, 649)
    assert not evaluate(w, prev(599), 549, True, 599)  # already below: no repeat


def test_drop_alert_threshold():
    w = Watch("Desk", "https://x", drop_pct=10)
    assert not evaluate(w, prev(700), 650, True, 700)  # -7%
    assert evaluate(w, prev(700), 620, True, 700)       # -11%


def test_restock_alert():
    w = Watch("Grinder", "https://x")
    assert any("back in stock" in a for a in evaluate(w, prev(389, False), 389, True, 389))
    assert not evaluate(w, prev(389, True), 389, True, 389)


# ---- fetching -----------------------------------------------------------------------
def fetcher_with(handler, **kw):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Fetcher("test-agent", retries=kw.get("retries", 2), min_delay=0, respect_robots=kw.get("robots", True), client=client)


def test_robots_txt_is_respected():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, text="ok")

    f = fetcher_with(handler)
    assert f.get("https://shop.test/item") == "ok"
    with pytest.raises(FetchError, match="robots"):
        f.get("https://shop.test/private/item")


def test_retries_server_errors_but_not_404(monkeypatch):
    monkeypatch.setattr("monitor.fetch.time.sleep", lambda s: None)
    calls = {"n": 0}

    def flaky(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200, text="finally")

    assert fetcher_with(flaky).get("https://shop.test/a") == "finally"

    calls["n"] = 0

    def missing(req):
        calls["n"] += 1
        return httpx.Response(404)

    with pytest.raises(FetchError, match="404"):
        fetcher_with(missing, robots=False).get("https://shop.test/gone")
    assert calls["n"] == 1


# ---- end to end -------------------------------------------------------------------
def test_failure_alert_after_n_failed_checks(tmp_path):
    cfg = Config(Settings(db_path=str(tmp_path / "p.sqlite"), alert_after_failures=3), [Watch("Gone", "https://shop.test/gone")])
    f = fetcher_with(lambda req: httpx.Response(404), robots=False)
    alerter = Alerter(env={})
    mon = Monitor(cfg, f, Store(cfg.settings.db_path), alerter)
    for _ in range(4):
        mon.run_once()
    assert len(alerter.sent) == 1 and "3 failed checks" in alerter.sent[0]


def test_demo_detects_every_event(tmp_path):
    mon = run_demo(db_path=str(tmp_path / "demo.sqlite"), quiet=True)
    text = "\n".join(mon.alerter.sent)
    assert len(mon.alerter.sent) == 6
    assert "Aurora ANC Headphones is A$199.00" in text      # target crossed
    assert "Conical Burr Grinder is back in stock" in text   # restock
    assert "Oak Standing Desk dropped 15%" in text           # % drop via CSS selector
    assert len(mon.store.history()) == 18


def test_config_validation(tmp_path):
    p = tmp_path / "w.toml"
    p.write_text('[[watch]]\nname = "A"\nurl = "https://a.test"\ntarget = 5\n')
    with pytest.raises(ValueError, match="target"):
        load_config(p)
    p.write_text('[[watch]]\nname = "A"\nurl = "ftp://a.test"\n')
    with pytest.raises(ValueError, match="http"):
        load_config(p)
