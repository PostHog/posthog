from datetime import UTC, datetime, timedelta

from django.conf import settings

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.constants import FlagRequestType
from posthog.dataclasses import frozen
from posthog.models.event.new_events_schema import events_read_table, use_new_events_schema
from posthog.models.property.util import get_property_string_expr
from posthog.utils import get_instance_region

from products.feature_flags.backend.flag_analytics import CACHE_BUCKET_SIZE, USAGE_EVENT_NAMES

COMPARISON_SETTINGS = {
    "max_execution_time": 30,
    "max_memory_usage": 1024 * 1024 * 1024,
    "max_bytes_to_read": 10 * 1024 * 1024 * 1024,
    "max_threads": 2,
}


@frozen
class FlagUsageComparison:
    exported_at: datetime
    source_start: datetime
    source_end: datetime
    legacy: int
    realtime: int


def compare_flag_usage_windows(
    *, team_id: int, export_day: datetime, request_type: FlagRequestType
) -> list[FlagUsageComparison]:
    if team_id <= 0 or export_day.tzinfo is None or export_day.utcoffset() != timedelta(0):
        raise ValueError("A positive team ID and UTC export date are required")
    if export_day != export_day.replace(hour=0, minute=0, second=0, microsecond=0):
        raise ValueError("The export date must start at UTC midnight")
    if request_type not in (FlagRequestType.DECIDE, FlagRequestType.LOCAL_EVALUATION):
        raise ValueError("Only billable flag request types have usage records")
    if not settings.DECIDE_BILLING_ANALYTICS_TOKEN:
        raise ValueError("DECIDE_BILLING_ANALYTICS_TOKEN is required")
    use_new = use_new_events_schema(None)
    expressions = {
        name: get_property_string_expr("events", name, f"'{name}'", "properties", use_new_events_schema=use_new)[0]
        for name in ("count", "min_time", "max_time", "token")
    }
    # nosemgrep: clickhouse-fstring-param-audit - schema and property expressions are internal fragments
    batches = sync_execute(
        f"""
        SELECT DISTINCT uuid, timestamp, toInt64OrZero({expressions["count"]}),
            toInt64OrZero({expressions["min_time"]}), toInt64OrZero({expressions["max_time"]})
        FROM {events_read_table(use_new)}
        WHERE team_id = %(internal_team_id)s AND distinct_id = toString(%(team_id)s)
          AND event = %(event)s AND {expressions["token"]} = %(token)s
          AND timestamp >= %(begin)s AND timestamp < %(end)s
        ORDER BY timestamp, uuid
        LIMIT 201
        """,
        {
            "internal_team_id": 1 if get_instance_region() == "EU" else 2,
            "team_id": team_id,
            "event": USAGE_EVENT_NAMES[request_type],
            "token": settings.DECIDE_BILLING_ANALYTICS_TOKEN,
            "begin": export_day,
            "end": export_day + timedelta(days=1),
        },
        workload=Workload.OFFLINE,
        ch_user=ClickHouseUser.BILLING,
        settings=COMPARISON_SETTINGS,
    )
    if len(batches) > 200:
        raise ValueError("More than 200 exports; use a narrower diagnostic query")
    for _, _, _, begin, last_bucket in batches:
        if begin <= 0 or last_bucket < begin or last_bucket + CACHE_BUCKET_SIZE - begin > 7 * 86400:
            raise ValueError("An export has invalid source bounds or spans more than seven days")
    usage_key = (
        "feature_flag_requests" if request_type == FlagRequestType.DECIDE else "feature_flag_local_evaluation_requests"
    )
    comparisons = []
    for _, exported_at, count, begin, last_bucket in batches:
        source_start = datetime.fromtimestamp(begin, UTC)
        source_end = datetime.fromtimestamp(last_bucket + CACHE_BUCKET_SIZE, UTC)
        rows = sync_execute(
            """
            SELECT sum(quantity), countIf(unit != 'requests')
            FROM billing_usage_records FINAL
            WHERE team_id = %(team_id)s AND usage_key = %(usage_key)s
              AND timestamp >= %(begin)s AND timestamp < %(end)s
            """,
            {"team_id": team_id, "usage_key": usage_key, "begin": source_start, "end": source_end},
            workload=Workload.OFFLINE,
            ch_user=ClickHouseUser.BILLING,
            settings=COMPARISON_SETTINGS,
        )
        realtime, invalid_units = rows[0]
        if invalid_units:
            raise ValueError("Usage records contain a unit other than requests")
        comparisons.append(
            FlagUsageComparison(
                exported_at=exported_at.replace(tzinfo=UTC) if exported_at.tzinfo is None else exported_at,
                source_start=source_start,
                source_end=source_end,
                legacy=int(count),
                realtime=int(realtime),
            )
        )
    return comparisons
