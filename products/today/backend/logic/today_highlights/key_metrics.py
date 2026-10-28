import json
from urllib.parse import quote

from products.customer_analytics.backend.facade.api import get_key_metrics
from products.customer_analytics.backend.facade.contracts import KeyMetric

from ...facade import contracts
from ...facade.enums import HighlightLabel, HighlightMetricReason, HighlightUnit
from ..highlight_rules import exact
from ..highlight_trends import detect
from ..highlight_types import Candidate, Context, DailyValueNotReady, Found, Source

KEY_METRIC_DAY = {
    True: "‘{name}’ increased by {pct}% yesterday",
    False: "‘{name}’ decreased by {pct}% yesterday",
}
KEY_METRIC_DAY_DETAIL = "{now} yesterday · {usual} on an average {weekday}"
KEY_METRIC_DAY_DETAIL_WEEK = "{now} yesterday · {usual} a day over the week before"
PULSE_DAYS = 28


def find(context: Context) -> Found:
    metrics = get_key_metrics(team=context.team, user=context.user)
    if metrics is None:
        raise DailyValueNotReady("key_metrics")
    shown = [metric for metric in metrics if metric.this_week or metric.last_week]
    candidates = [candidate for metric in shown if (candidate := _same_weekday(context, metric)) is not None]
    return Found(items=tuple(candidates), pulse=tuple(tile(metric) for metric in shown))


def tile(metric: KeyMetric) -> contracts.HighlightMetric:
    return contracts.HighlightMetric(
        key=metric.key,
        name=metric.name,
        value=metric.this_week,
        unit=HighlightUnit.PEOPLE if metric.people else HighlightUnit.EVENTS,
        change_pct=round((metric.this_week / metric.last_week - 1) * 100, 1) if metric.last_week else None,
        series=[v for _, v in metric.daily[-PULSE_DAYS:]],
        url=_url(metric),
        reason=HighlightMetricReason.KEY_METRIC,
        previous_value=metric.last_week,
    )


def _url(metric: KeyMetric) -> str | None:
    days = [day for day, _ in metric.daily[-PULSE_DAYS:]]
    if not days:
        return None
    query = {
        "kind": "InsightVizNode",
        "source": {
            "kind": "TrendsQuery",
            "series": [{**metric.node, "math": "dau" if metric.people else "total"}],
            "interval": "day",
            "dateRange": {"date_from": days[0].isoformat(), "date_to": days[-1].isoformat()},
            "filterTestAccounts": True,
        },
    }
    return f"/insights/new#q={quote(json.dumps(query, separators=(',', ':')))}"


def _same_weekday(context: Context, metric: KeyMetric) -> Candidate | None:
    detections, _ = detect(metric.daily, "day", context.today)
    found = next((d for d in detections if d.kind == "same_weekday"), None)
    if found is None:
        return None
    up = found.direction > 0
    return Candidate(
        key=f"key_metric:{metric.key}",
        label=HighlightLabel.OPPORTUNITY if up else HighlightLabel.RISK,
        family="key_metrics",
        importance=0.95 * found.strength,
        relevance=0.6,
        title=KEY_METRIC_DAY[up].format(name=metric.name, pct=f"{abs(found.pct or 0):.0f}"),
        detail=(KEY_METRIC_DAY_DETAIL if found.same_weekday else KEY_METRIC_DAY_DETAIL_WEEK).format(
            now=exact(found.now or 0), usual=exact(found.usual or 0, 0), weekday=found.weekday
        ),
        url=_url(metric),
        series=[v for _, v in metric.daily[-14:]],
    )


SOURCE = Source(name="key_metrics", find=find, scopes=("customer_analytics:read",), pulse_order=2)
