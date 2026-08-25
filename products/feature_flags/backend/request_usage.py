import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Literal, cast

from django.conf import settings

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.event.new_events_schema import events_read_table, use_new_events_schema
from posthog.models.property.util import get_property_string_expr
from posthog.utils import get_instance_region


class FeatureFlagRequestType(StrEnum):
    REMOTE_EVALUATION = "remote_evaluation"
    LOCAL_EVALUATION = "local_evaluation"


@frozen
class FeatureFlagRequestUsage:
    bucket: datetime
    request_type: FeatureFlagRequestType
    sdk: str
    request_count: int
    billing_units: int


REQUEST_USAGE_QUERY_SETTINGS = {
    "max_execution_time": 30,
    "max_bytes_to_read": 10 * 1024 * 1024 * 1024,
    "max_memory_usage": 2 * 1024 * 1024 * 1024,
    "max_threads": 4,
}

FeatureFlagRequestUsageRow = tuple[datetime, Literal["remote_evaluation", "local_evaluation"], int, str]


def parse_sdk_breakdown(raw_sdk_breakdown: str) -> dict[str, int]:
    try:
        parsed_breakdown = json.loads(raw_sdk_breakdown) if raw_sdk_breakdown else {}
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed_breakdown, dict):
        return {}
    return {
        sdk: count
        for sdk, count in parsed_breakdown.items()
        if isinstance(sdk, str) and isinstance(count, int) and count >= 0
    }


def aggregate_feature_flag_request_usage(
    rows: Iterable[FeatureFlagRequestUsageRow],
) -> list[FeatureFlagRequestUsage]:
    counts: defaultdict[tuple[datetime, FeatureFlagRequestType, str], int] = defaultdict(int)
    for bucket, raw_request_type, total_count, raw_sdk_breakdown in rows:
        request_type = FeatureFlagRequestType(raw_request_type)
        sdk_breakdown = parse_sdk_breakdown(raw_sdk_breakdown)
        for sdk, count in sdk_breakdown.items():
            counts[(bucket, request_type, sdk)] += count
        counts[(bucket, request_type, "other")] += max(total_count - sum(sdk_breakdown.values()), 0)

    return [
        FeatureFlagRequestUsage(
            bucket=bucket,
            request_type=request_type,
            sdk=sdk,
            request_count=request_count,
            billing_units=request_count * (10 if request_type == FeatureFlagRequestType.LOCAL_EVALUATION else 1),
        )
        for (bucket, request_type, sdk), request_count in sorted(counts.items())
        if request_count > 0
    ]


def query_feature_flag_request_usage(
    *, team_id: int, date_from: datetime, date_to: datetime, time_interval: Literal["hour", "day"]
) -> list[FeatureFlagRequestUsage]:
    internal_team_id = 1 if get_instance_region() == "EU" else 2
    validity_token = settings.DECIDE_BILLING_ANALYTICS_TOKEN
    use_new = use_new_events_schema(None)
    sdk_breakdown_expr, _ = get_property_string_expr(
        "events", "sdk_breakdown", "'sdk_breakdown'", "properties", use_new_events_schema=use_new
    )
    count_expr, _ = get_property_string_expr("events", "count", "'count'", "properties", use_new_events_schema=use_new)
    token_expr, _ = get_property_string_expr("events", "token", "'token'", "properties", use_new_events_schema=use_new)
    bucket_function = "toStartOfHour" if time_interval == "hour" else "toStartOfDay"

    with tags_context(product=Product.FEATURE_FLAGS, feature=Feature.QUERY, team_id=team_id):
        # nosemgrep: clickhouse-fstring-param-audit - bucket function and table expressions are internal allowlisted fragments
        rows = sync_execute(
            f"""
            SELECT
                {bucket_function}(timestamp) AS bucket,
                if(event = 'decide usage', 'remote_evaluation', 'local_evaluation') AS request_type,
                toInt64OrZero({count_expr}) AS total_count,
                {sdk_breakdown_expr} AS sdk_breakdown
            FROM {events_read_table(use_new)}
            WHERE team_id = %(internal_team_id)s
              AND distinct_id = toString(%(team_id)s)
              AND event IN ('decide usage', 'local evaluation usage')
              AND timestamp >= %(date_from)s AND timestamp < %(date_to)s
              AND has([%(validity_token)s], {token_expr})
            ORDER BY bucket, request_type
            """,
            {
                "internal_team_id": internal_team_id,
                "team_id": team_id,
                "date_from": date_from,
                "date_to": date_to,
                "validity_token": validity_token,
            },
            workload=Workload.ONLINE,
            team_id=team_id,
            settings=REQUEST_USAGE_QUERY_SETTINGS,
            ch_user=ClickHouseUser.APP,
        )

    return aggregate_feature_flag_request_usage(cast(list[FeatureFlagRequestUsageRow], rows))
