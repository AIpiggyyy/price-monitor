"""Read price and stock status out of a product page.

Order of attempts:
1. CSS selector from the watch config (exact control for odd sites)
2. JSON-LD structured data (schema.org Product/Offer) - most online shops publish this for Google
3. Meta tags (Open Graph `product:price:amount`, `og:price:amount`, `itemprop="price"`)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup


@dataclass
class Extracted:
    price: float | None
    in_stock: bool | None
    currency: str | None
    method: str            # which extractor found the price
    title: str | None = None


_NUM = re.compile(r"\d[\d.,\s]*")


def parse_price(text: str | float | int | None) -> float | None:
    """Turn '$1,299.00', '1.299,00 €', 'A$49', 'From $10.50' or 1299 into a float."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    m = _NUM.search(str(text).replace(" ", " "))
    if not m:
        return None
    s = m.group(0).strip().replace(" ", "")
    if "," in s and "." in s:
        # the last separator is the decimal one: 1,299.00 vs 1.299,00
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = s.replace(",", ".") if len(tail) in (1, 2) else s.replace(",", "")  # 12,5 / 12,50 vs 1,299
    elif s.count(".") > 1:
        s = s.replace(".", "")  # 1.299.000
    try:
        return float(s)
    except ValueError:
        return None


def _availability(value) -> bool | None:
    if value is None:
        return None
    v = str(value).lower()
    if any(k in v for k in ("outofstock", "soldout", "discontinued", "out of stock", "sold out")):
        return False
    if any(k in v for k in ("instock", "in stock", "limitedavailability", "preorder", "backorder", "onlineonly")):
        return True
    return None


def _walk_jsonld(node):
    if isinstance(node, list):
        for n in node:
            yield from _walk_jsonld(n)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "offers", "hasVariant", "itemListElement", "mainEntity"):
            if key in node:
                yield from _walk_jsonld(node[key])


def from_jsonld(soup: BeautifulSoup) -> Extracted | None:
    title = None
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _walk_jsonld(data):
            types = node.get("@type", "")
            types = types if isinstance(types, list) else [types]
            if "Product" in types and not title:
                title = node.get("name")
            if any(t in ("Offer", "AggregateOffer") for t in types):
                price = parse_price(node.get("price") or node.get("lowPrice"))
                if price is not None:
                    return Extracted(price, _availability(node.get("availability")), node.get("priceCurrency"), "json-ld", title)
    return None


def from_meta(soup: BeautifulSoup) -> Extracted | None:
    def meta(*names):
        for n in names:
            t = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n}) or soup.find(attrs={"itemprop": n})
            if t:
                return t.get("content") or t.get_text(strip=True)
        return None

    price = parse_price(meta("product:price:amount", "og:price:amount", "price"))
    if price is None:
        return None
    return Extracted(
        price,
        _availability(meta("product:availability", "og:availability", "availability")),
        meta("product:price:currency", "og:price:currency", "priceCurrency"),
        "meta",
        meta("og:title"),
    )


def from_selector(soup: BeautifulSoup, price_sel: str | None, stock_sel: str | None, oos_text: str) -> Extracted | None:
    price = None
    if price_sel:
        el = soup.select_one(price_sel)
        if el is None:
            return None
        price = parse_price(el.get("content") or el.get_text(" ", strip=True))
    in_stock = None
    if stock_sel:
        el = soup.select_one(stock_sel)
        if el is not None:
            in_stock = oos_text.lower() not in el.get_text(" ", strip=True).lower()
    if price is None and in_stock is None:
        return None
    return Extracted(price, in_stock, None, "css")


def extract(html: str, price_selector: str | None = None, stock_selector: str | None = None,
            out_of_stock_text: str = "out of stock") -> Extracted:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else None
    found = None
    if price_selector or stock_selector:
        found = from_selector(soup, price_selector, stock_selector, out_of_stock_text)
        if found and found.price is None:  # stock from selector, price from structured data
            structured = from_jsonld(soup) or from_meta(soup)
            if structured:
                found.price, found.currency, found.method = structured.price, structured.currency, f"css+{structured.method}"
    if found is None or found.price is None:
        found = from_jsonld(soup) or from_meta(soup) or found
    if found is None:
        return Extracted(None, None, None, "none", title)
    found.title = found.title or title
    return found
