import re
from datetime import date

from products.product_analytics.backend.facade.contracts import InsightSeries

from .highlight_trends import UNCLEAR_LABEL, stale


def human(value: float) -> str:
    size = abs(value)
    if size >= 999_500:
        return f"{value / 1_000_000:.1f}M"
    if size >= 9_950:
        return f"{value / 1000:.0f}k"
    if size >= 999.5:
        return f"{value / 1000:.1f}k"
    return f"{value:.0f}" if size >= 10 or float(value).is_integer() else f"{value:.1f}"


def exact(value: float) -> str:
    return f"{value:,.0f}" if abs(value) < 100_000 else human(value)


def pretty(name: str) -> str:
    if re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)+", name):
        name = name.replace("_", " ")
        return name[0].upper() + name[1:]
    return name


def short(text: str, limit: int = 60) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).replace('"', "").strip()
    text = re.sub(r"'([^']*)'", "‘\\1’", text).replace("'", "’")
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:(-– ")


def usable_series(insight: InsightSeries, today: date) -> dict[str, list[tuple[date, float]]]:
    unclear = len(insight.series) > 1 or not insight.name
    return {
        name: points
        for name, points in insight.series.items()
        if "@" not in name
        and not (unclear and UNCLEAR_LABEL.search(name.strip()))
        and not stale(points, insight.period, today)
    }
