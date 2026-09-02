"""Per-hour flag request counts, recorded to `app_metrics2`.

The billing pipeline reduces flag requests to one number per team per period, which cannot
answer "why is my volume this high". These rows carry the same counts split by request type
and SDK, so a project can see the shape of its own traffic.

The rows are diagnostic only. Billing keeps reading the Redis counters through
`capture_team_decide_usage`, never this table.
"""

from collections import defaultdict
from datetime import UTC, datetime

from django.conf import settings

from posthog.constants import FlagRequestType
from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_APP_METRICS2
from posthog.models.event.util import format_clickhouse_timestamp

APP_SOURCE = "feature_flags"

# The total counter and the per-SDK counters are incremented by separate Redis writes, so the
# per-SDK counts can add up to less than the total. The difference is recorded under this name
# to keep the sum over `metric_name` equal to the request count that billing reads.
UNATTRIBUTED_LIBRARY = "unattributed"


def record_request_metrics(
    team_id: int,
    request_type: FlagRequestType,
    total_counts_by_time: dict[int, int],
    library_counts_by_time: dict[str, dict[int, int]],
) -> None:
    """Record one `app_metrics2` row per (hour, SDK) for one team and request type.

    Both count maps are keyed by unix epoch seconds. Counts that fall in the same hour are
    added together here, because `app_metrics2` sorts on the hour and one row per Redis
    bucket would be up to 30 rows for the same hour.

    This function never raises. The caller sends the billing event from the same drained
    counters, and a diagnostic write must not put that at risk.
    """
    if not settings.FLAG_REQUEST_METRICS_ENABLED:
        return

    try:
        totals_by_hour: dict[datetime, int] = defaultdict(int)
        for epoch_seconds, count in total_counts_by_time.items():
            totals_by_hour[_start_of_hour(epoch_seconds)] += count

        libraries_by_hour: dict[datetime, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for library, counts_by_time in library_counts_by_time.items():
            for epoch_seconds, count in counts_by_time.items():
                libraries_by_hour[_start_of_hour(epoch_seconds)][library] += count

        producer = get_producer(topic=KAFKA_APP_METRICS2)
        for hour in sorted(set(totals_by_hour) | set(libraries_by_hour)):
            rows = _rows_for_hour(totals_by_hour.get(hour, 0), libraries_by_hour.get(hour, {}))
            for metric_name, count in rows:
                producer.produce(
                    topic=KAFKA_APP_METRICS2,
                    data={
                        "team_id": team_id,
                        "timestamp": format_clickhouse_timestamp(hour),
                        "app_source": APP_SOURCE,
                        # Flag requests belong to the whole project, so there is no sub-object to
                        # key on. The read path matches `app_source_id` exactly, so it must agree.
                        "app_source_id": "",
                        # Reserved for the SDK version, which is not carried past the flags service
                        # yet.
                        "instance_id": "",
                        "metric_kind": str(request_type),
                        "metric_name": metric_name,
                        "count": count,
                    },
                )
    except Exception as error:
        capture_exception(error)


def _start_of_hour(epoch_seconds: int) -> datetime:
    return datetime.fromtimestamp(epoch_seconds, tz=UTC).replace(minute=0, second=0, microsecond=0)


def _rows_for_hour(total: int, library_counts: dict[str, int]) -> list[tuple[str, int]]:
    rows = [(library, count) for library, count in sorted(library_counts.items()) if count > 0]
    # A negative remainder would mean the per-SDK counters ran ahead of the total. Recording it
    # would push the sum over the count billing reads, so the row is dropped instead.
    unattributed = total - sum(count for _, count in rows)
    if unattributed > 0:
        rows.append((UNATTRIBUTED_LIBRARY, unattributed))
    return rows
