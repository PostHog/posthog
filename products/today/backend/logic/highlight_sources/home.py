from functools import partial

from products.dashboards.backend.facade.api import home_dashboard_insights
from products.product_analytics.backend.facade.api import get_insight_series
from products.product_analytics.backend.facade.contracts import InsightDashboardContext

from ...facade.enums import HighlightLabel
from ..highlight_rules import exact, pretty, short, usable_series
from ..highlight_trends import BAD_METRIC, MONEY, UNKNOWN_DIRECTION, detect
from ..highlight_types import Candidate, Context, Found, Source

HOME_WORSE = {
    True: "‘{name}’ increased by {pct}% last {period}",
    False: "‘{name}’ decreased by {pct}% last {period}",
}
HOME_WORSE_SERIES = {
    True: "‘{name}’ ({series}) increased by {pct}% last {period}",
    False: "‘{name}’ ({series}) decreased by {pct}% last {period}",
}
CHANGE = "{before} → {now}"
CHANGE_DAILY = "{before} → {now} a day on average"

HOME_TILES = 4
MIN_CHANGE_PCT = 15
MIN_VALUE = 200
MIN_DIFFERENCE = 50


def find(context: Context) -> Found:
    home = home_dashboard_insights(team=context.team, user=context.user, limit=HOME_TILES)
    if home is None:
        return Found()
    found = [
        context.guard(
            f"tile {tile.insight_short_id}",
            partial(
                _tile,
                context,
                tile.insight_short_id,
                InsightDashboardContext(
                    filters=home.filters, tile_filters=tile.filters_overrides, variables=home.variables
                ),
            ),
            None,
        )
        for tile in home.tiles
    ]
    return Found(items=tuple(candidate for candidate in found if candidate is not None))


def _tile(context: Context, short_id: str, dashboard: InsightDashboardContext) -> Candidate | None:
    insight = get_insight_series(team=context.team, user=context.user, short_id=short_id, dashboard=dashboard)
    if insight is None:
        return None
    series = usable_series(insight, context.today)
    if not series:
        return None
    period = insight.period
    name, points = max(series.items(), key=lambda item: sum(abs(v) for _, v in item[1]))
    average = period == "day" and name in insight.averaged_series
    detections, values = detect(points, period, context.today, average)
    if len(values) < 2 or values[-1] == 0 or (values[-2] and values[-1] / values[-2] <= 0.02):
        return None
    label = f"{insight.name} {name} {insight.event_name}"
    money = bool(MONEY.search(label))
    if abs(values[-1]) < 10 and not money:
        return None
    if not values[-2] or (detections and all(d.kind == "flatline" for d in detections)):
        return None
    change = (values[-1] / values[-2] - 1) * 100
    bad = bool(BAD_METRIC.search(label))
    if abs(change) < MIN_CHANGE_PCT or (change > 0) != bad or (not bad and UNKNOWN_DIRECTION.search(label)):
        return None
    if not money and (max(values[-1], values[-2]) < MIN_VALUE or abs(values[-1] - values[-2]) < MIN_DIFFERENCE):
        return None
    measured = short(pretty(name), 30) if len(series) > 1 and insight.name else ""
    return Candidate(
        key=f"home:{short_id}",
        label=HighlightLabel.RISK,
        family="home",
        importance=0.6,
        relevance=1.0,
        title=(HOME_WORSE_SERIES if measured else HOME_WORSE)[change > 0].format(
            name=short(insight.name or pretty(name), 60),
            series=measured,
            pct=f"{abs(round(change, 1)):.0f}",
            period="month" if period == "month" else "week",
        ),
        detail=(CHANGE_DAILY if average else CHANGE).format(now=exact(values[-1]), before=exact(values[-2])),
        url=f"/insights/{short_id}",
        ref=short_id,
        series=values[-8:],
    )


SOURCE = Source(name="home", find=find, scopes=("dashboard:read", "insight:read"))
