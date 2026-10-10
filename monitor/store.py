"""Price history in SQLite (one file, no server)."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Check:
    ts: float
    watch: str
    price: float | None
    in_stock: bool | None
    ok: bool
    error: str = ""
    method: str = ""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS checks (
                    ts REAL, watch TEXT, price REAL, in_stock INTEGER, ok INTEGER, error TEXT, method TEXT)"""
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_watch_ts ON checks(watch, ts)")

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def add(self, c: Check) -> None:
        with self._db() as db:
            db.execute(
                "INSERT INTO checks VALUES (?,?,?,?,?,?,?)",
                (c.ts or time.time(), c.watch, c.price, None if c.in_stock is None else int(c.in_stock), int(c.ok), c.error, c.method),
            )

    def last_ok(self, watch: str) -> Check | None:
        with self._db() as db:
            row = db.execute(
                "SELECT ts, watch, price, in_stock, ok, error, method FROM checks WHERE watch=? AND ok=1 ORDER BY ts DESC LIMIT 1",
                (watch,),
            ).fetchone()
        return _row(row) if row else None

    def failures_in_a_row(self, watch: str) -> int:
        with self._db() as db:
            rows = db.execute("SELECT ok FROM checks WHERE watch=? ORDER BY ts DESC LIMIT 50", (watch,)).fetchall()
        n = 0
        for (ok,) in rows:
            if ok:
                break
            n += 1
        return n

    def history(self, watch: str | None = None) -> list[Check]:
        q = "SELECT ts, watch, price, in_stock, ok, error, method FROM checks"
        args: tuple = ()
        if watch:
            q, args = q + " WHERE watch=?", (watch,)
        with self._db() as db:
            return [_row(r) for r in db.execute(q + " ORDER BY ts", args).fetchall()]

    def lowest(self, watch: str) -> float | None:
        with self._db() as db:
            (v,) = db.execute("SELECT MIN(price) FROM checks WHERE watch=? AND ok=1", (watch,)).fetchone()
        return v


def _row(r) -> Check:
    return Check(ts=r[0], watch=r[1], price=r[2], in_stock=None if r[3] is None else bool(r[3]), ok=bool(r[4]), error=r[5] or "", method=r[6] or "")
