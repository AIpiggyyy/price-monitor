"""Exports and charts from the price history."""
from __future__ import annotations

import csv
from datetime import datetime, timezone

from .store import Store


def export_csv(store: Store, path: str, watch: str | None = None) -> int:
    rows = store.history(watch)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_utc", "watch", "price", "in_stock", "ok", "error", "method"])
        for c in rows:
            w.writerow([datetime.fromtimestamp(c.ts, timezone.utc).isoformat(timespec="seconds"), c.watch, c.price,
                        c.in_stock, c.ok, c.error, c.method])
    return len(rows)


def chart(store: Store, watches: list[str], path: str, currency: str = "$", targets: dict[str, float] | None = None) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    colors = ["#1d4ed8", "#c2410c", "#047857", "#7c3aed", "#be185d"]
    fig, axes = plt.subplots(len(watches), 1, figsize=(9, 2.3 * len(watches)), sharex=True, squeeze=False)
    for ax, name, color in zip(axes[:, 0], watches, colors * 3):
        hist = [c for c in store.history(name) if c.ok and c.price is not None]
        if not hist:
            continue
        t = [datetime.fromtimestamp(c.ts, timezone.utc) for c in hist]
        p = [c.price for c in hist]
        ax.step(t, p, where="post", color=color, lw=2)
        ax.scatter(t, p, color=color, s=14, zorder=3)
        labelled = False
        for j, c in enumerate(hist):
            if c.in_stock is False:
                end = t[j + 1] if j + 1 < len(t) else t[j]
                ax.axvspan(t[j], end, color="#b91c1c", alpha=0.10, lw=0)
                if not labelled:
                    ax.annotate("out of stock", (t[j], c.price), xytext=(4, 6), textcoords="offset points", fontsize=8, color="#b91c1c")
                    labelled = True
        target = (targets or {}).get(name)
        if target:
            ax.axhline(target, color="#6b7280", lw=1, ls="--")
            ax.annotate(f"target {currency}{target:,.0f}", (t[0], target), xytext=(2, -11), textcoords="offset points", fontsize=8, color="#4b5563")
            p = p + [target]
        ax.set_title(name, loc="left", fontsize=10)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{currency}{v:,.0f}"))
        ax.grid(alpha=0.25)
        lo, hi = min(p), max(p)
        ax.set_ylim(lo - (hi - lo) * 0.25 - 1, hi + (hi - lo) * 0.25 + 1)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    axes[-1, 0].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
