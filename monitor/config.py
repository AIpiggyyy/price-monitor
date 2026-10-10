"""Watch list and settings, from one TOML file. Secrets come from environment variables."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


def load_dotenv(path: Path) -> None:
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass
class Watch:
    name: str
    url: str
    # How to read the price. "auto" tries structured data (JSON-LD, then meta tags).
    # Give a CSS selector for sites without structured data.
    price_selector: str | None = None
    stock_selector: str | None = None        # element whose text says in/out of stock
    out_of_stock_text: str = "out of stock"  # matched case-insensitively in stock_selector
    target_price: float | None = None        # alert when price <= target
    drop_pct: float | None = None            # alert when price falls this % vs last check
    alert_restock: bool = True
    currency: str = ""                       # display only, e.g. "A$"


@dataclass
class Settings:
    interval_minutes: int = 60
    db_path: str = "data/prices.sqlite"
    user_agent: str = "price-monitor/1.0 (+https://github.com/AIpiggyyy/price-monitor)"
    timeout_s: float = 20.0
    retries: int = 2
    min_delay_per_domain_s: float = 5.0      # be polite: never hit one site faster than this
    respect_robots_txt: bool = True
    alert_after_failures: int = 3            # alert if a page fails this many checks in a row


@dataclass
class Config:
    settings: Settings = field(default_factory=Settings)
    watches: list[Watch] = field(default_factory=list)


def _build(cls, data: dict, where: str):
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"Unknown setting(s) in {where}: {', '.join(sorted(unknown))}")
    return cls(**data)


def load_config(path: str | Path) -> Config:
    path = Path(path)
    load_dotenv(path.parent / ".env")
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    settings = _build(Settings, raw.get("settings", {}), "[settings]")
    watches = [_build(Watch, w, f"[[watch]] #{i + 1}") for i, w in enumerate(raw.get("watch", []))]
    names = [w.name for w in watches]
    if len(names) != len(set(names)):
        raise ValueError("Each [[watch]] needs a unique name")
    for w in watches:
        if not w.url.startswith(("http://", "https://")):
            raise ValueError(f"{w.name}: url must start with http:// or https://")
    return Config(settings, watches)
