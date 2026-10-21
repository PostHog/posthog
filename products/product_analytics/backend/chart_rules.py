from typing import Any

UNCHARTED_DISPLAYS = {
    "ActionsTable",
    "ActionsPie",
    "BoldNumber",
    "WorldMap",
    "ActionsBarValue",
    "ActionsLineGraphCumulative",
    "SlopeGraph",
}
CHARTED_SQL_DISPLAYS = {"ActionsLineGraph", "ActionsBar", "ActionsStackedBar", "ActionsAreaGraph"}
LOOKBACK = {"day": "-56d", "week": "-16w", "month": "-24m"}


def is_chartable(query: dict[str, Any], interval: str | None = None) -> bool:
    source = query.get("source", query)
    if query.get("kind") == "DataVisualizationNode" and source.get("kind") == "HogQLQuery":
        settings = query.get("chartSettings") or {}
        return (
            query.get("display") in CHARTED_SQL_DISPLAYS
            and bool((settings.get("xAxis") or {}).get("column"))
            and any(axis.get("column") for axis in settings.get("yAxis") or [])
        )
    trends = source.get("trendsFilter") or {}
    if source.get("kind") != "TrendsQuery" or trends.get("display") in UNCHARTED_DISPLAYS:
        return False
    return not (series_interval(source, interval) == "day" and (source.get("dateRange") or {}).get("daysOfWeek"))


def series_interval(source: dict[str, Any], override: str | None) -> str:
    interval = override or source.get("interval") or "day"
    return interval if interval in LOOKBACK else "day"
