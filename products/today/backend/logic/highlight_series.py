import re
from datetime import date

from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP

from products.product_analytics.backend.facade.contracts import InsightSeries

from .highlight_trends import UNCLEAR_LABEL, stale

CORE_EVENTS = CORE_FILTER_DEFINITIONS_BY_GROUP["events"]


def pretty(name: str) -> str:
    event, separator, rest = name.partition(" · ")
    if event in CORE_EVENTS:
        return f"{CORE_EVENTS[event]['label']}{separator}{rest}"
    if re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)+", name):
        name = name.replace("_", " ")
        return name[0].upper() + name[1:]
    return name


def usable_series(insight: InsightSeries, today: date) -> dict[str, list[tuple[date, float]]]:
    unclear = len(insight.series) > 1 or not insight.name
    return {
        name: points
        for name, points in insight.series.items()
        if "@" not in name
        and not (unclear and UNCLEAR_LABEL.search(pretty(name).strip()))
        and not stale(points, insight.period, today)
    }
