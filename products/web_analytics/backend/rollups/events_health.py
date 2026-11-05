from typing import Any

from posthog.clickhouse.query_tagging import Product
from posthog.temporal.health_checks.rollups.framework import DailyRollup

from products.web_analytics.backend.models.health_rollups import EventsHealthDaily, SessionIdState
from products.web_analytics.backend.rollups.properties import has_event_property

EVENTS_HEALTH_EVENTS = ("$pageview", "$screen", "$pageleave", "$web_vitals")

EVENTS_HEALTH_FILL_SQL = """
SELECT
    team_id,
    event,
    {has_custom_api_host} AS has_custom_api_host,
    event = '$pageleave' AND {has_scroll_depth} AS has_scroll_depth,
    multiIf(
        event != '$pageview', {not_applicable},
        `$session_id_uuid` IS NULL, {absent_or_not_uuid},
        bitAnd(bitShiftRight(`$session_id_uuid`, 76), 0xF) != 7, {not_uuidv7},
        {valid}
    ) AS session_id_state,
    count() AS event_count
FROM events
WHERE team_id >= %(team_id_start)s
  AND team_id < %(team_id_end)s
  AND timestamp >= %(day_start)s
  AND timestamp < %(day_end)s
  AND event IN %(events)s
GROUP BY team_id, event, has_custom_api_host, has_scroll_depth, session_id_state
"""


class EventsHealthDailyRollup(DailyRollup):
    model = EventsHealthDaily
    product = Product.WEB_ANALYTICS
    columns = (
        "team_id",
        "day",
        "event",
        "has_custom_api_host",
        "has_scroll_depth",
        "session_id_state",
        "event_count",
    )
    retention_days = 35

    @classmethod
    def fill_sql(cls) -> str:
        return EVENTS_HEALTH_FILL_SQL.format(
            has_custom_api_host=has_event_property("$lib_custom_api_host"),
            has_scroll_depth=has_event_property("$prev_pageview_max_content_percentage"),
            not_applicable=SessionIdState.NOT_APPLICABLE.value,
            absent_or_not_uuid=SessionIdState.ABSENT_OR_NOT_UUID.value,
            not_uuidv7=SessionIdState.NOT_UUIDV7.value,
            valid=SessionIdState.VALID.value,
        )

    @classmethod
    def fill_params(cls) -> dict[str, Any]:
        return {"events": list(EVENTS_HEALTH_EVENTS)}
