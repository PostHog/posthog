import json
from functools import partial
from urllib.parse import quote, urlencode

from products.dashboards.backend.facade.api import home_dashboard_insights
from products.product_analytics.backend.facade.api import get_insight_series
from products.product_analytics.backend.facade.contracts import InsightDashboardContext

from ...facade.enums import HighlightLabel
from ..highlight_rules import exact, short
from ..highlight_series import pretty, usable_series
from ..highlight_trends import BAD_METRIC, MONEY, UNKNOWN_DIRECTION, detect
from ..highlight_types import Candidate, Context, Found, Source

HOME_WORSE = "‘{name}’ {moved} by {pct}% last {period}"
HOME_WORSE_SERIES = "‘{name}’ ({series}) {moved} by {pct}% last {period}"
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
                home.dashboard_id,
                InsightDashboardContext(
                    filters=home.filters, tile_filters=tile.filters_overrides, variables=home.variables
                ),
            ),
            None,
        )
        for tile in home.tiles
    ]
    return Found(items=tuple(candidate for candidate in found if candidate is not None))


def _url(short_id: str, dashboard_id: int, dashboard: InsightDashboardContext) -> str:
    overrides = {
        "variables_override": dashboard.variables,
        "filters_override": dashboard.filters,
        "tile_filters_override": dashboard.tile_filters,
    }
    params = {"dashboard": dashboard_id} | {
        key: json.dumps(value, separators=(",", ":")) for key, value in overrides.items() if value
    }
    return f"/insights/{short_id}?{urlencode(params, quote_via=quote)}"


def _tile(context: Context, short_id: str, dashboard_id: int, dashboard: InsightDashboardContext) -> Candidate | None:
    insight = get_insight_series(team=context.team, user=context.user, short_id=short_id, dashboard=dashboard)
    if insight is None:
        return None
    series = usable_series(insight, context.today)
    if not series:
        return None
    period = insight.period
    name, points = max(series.items(), key=lambda item: sum(abs(v) for _, v in item[1]))
    average = period == "day" and name in insight.averaged_series
    _, values = detect(points, period, context.today, average)
    if len(values) < 2:
        return None
    now, before = values[-1], values[-2]
    if not now or not before or 0 < now / before <= 0.02:
        return None
    label = f"{insight.name} {name} {insight.event_name}"
    money = insight.value_format == "currency" or bool(MONEY.search(label))
    if abs(now) < 10 and not money:
        return None
    change = (now - before) / abs(before) * 100
    bad = bool(BAD_METRIC.search(label))
    if abs(change) < MIN_CHANGE_PCT or (change > 0) != bad or (not bad and UNKNOWN_DIRECTION.search(label)):
        return None
    if not money and (max(abs(now), abs(before)) < MIN_VALUE or abs(now - before) < MIN_DIFFERENCE):
        return None
    measured = short(pretty(name), 30) if len(series) > 1 and insight.name else ""
    return Candidate(
        key=f"home:{short_id}",
        label=HighlightLabel.RISK,
        family="home",
        importance=0.6,
        relevance=1.0,
        title=(HOME_WORSE_SERIES if measured else HOME_WORSE).format(
            name=short(insight.name or pretty(name), 60),
            series=measured,
            moved="increased" if change > 0 else "decreased",
            pct=f"{abs(change):.0f}",
            period="month" if period == "month" else "week",
        ),
        detail=(CHANGE_DAILY if average else CHANGE).format(
            now=exact(now, insight.decimal_places), before=exact(before, insight.decimal_places)
        ),
        url=_url(short_id, dashboard_id, dashboard),
        ref=short_id,
        series=values[-8:],
    )


SOURCE = Source(name="home", find=find, scopes=("dashboard:read", "insight:read"))
