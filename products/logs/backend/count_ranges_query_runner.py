import datetime as dt
from functools import cached_property

from posthog.schema import CachedLogsQueryResponse, DateRange, LogsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.logs.backend.agent_window import utc_iso
from products.logs.backend.logs_query_runner import (
    LogsQueryResponse,
    LogsQueryRunnerMixin,
    fail_fast_aggregate_settings,
)
from products.logs.backend.onset_detection import find_onset

DEFAULT_TARGET_BUCKETS = 10
MAX_TARGET_BUCKETS = 100


class LogsDetectMode(LabeledStrEnum):
    ONSET = "onset"


DETECT_MODES = LogsDetectMode.values


@frozen
class _Grid:
    starts: list[dt.datetime]
    counts: list[int]
    step: dt.timedelta


ONSET_FINE_TARGET_BUCKETS = 24
ONSET_HIGH_CONFIDENCE_BASELINE = 12


def _utc_z(value: dt.datetime) -> str:
    """Format a naive UTC datetime as a Z-suffixed ISO 8601 string."""
    return value.replace(tzinfo=dt.UTC).isoformat().replace("+00:00", "Z")


class CountRangesQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Returns adaptive-interval bucket counts for a filtered log stream.

    Each bucket carries explicit `date_from` / `date_to` so an agent can copy the
    range into a follow-up call without reasoning about interval width.
    """

    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    def __init__(self, *args, target_buckets: int = DEFAULT_TARGET_BUCKETS, detect: str | None = None, **kwargs):
        # Set before super().__init__ so query_date_range (cached) sees the override
        # the first time it's read.
        self.BUCKET_TARGET = max(1, min(target_buckets, MAX_TARGET_BUCKETS))
        self.detect = detect
        super().__init__(*args, **kwargs)

    def get_cache_payload(self) -> dict:
        return {**super().get_cache_payload(), "target_buckets": self.BUCKET_TARGET, "detect": self.detect}

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        return fail_fast_aggregate_settings(max_bytes_to_read=1_000_000_000)

    def _calculate(self) -> LogsQueryResponse:
        ranges = self._ranges()
        results: dict = {"ranges": ranges, "interval": self._interval_short()}
        if self.detect == "onset":
            results["onset"] = self._onset(ranges)
        return LogsQueryResponse(results=results)

    def _ranges(self) -> list[dict]:
        response = execute_hogql_query(
            query_type="LogsQuery",
            query=self.to_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            settings=self.settings,
        )

        ranges: list[dict] = []
        for row in response.results:
            # ClickHouse returns naive datetimes holding UTC values. Emit explicit UTC
            # (Z-suffixed) ISO strings so a bucket's date_from/date_to can be fed straight
            # back into query-logs without timezone drift.
            bucket_start: dt.datetime = row[0]
            bucket_end: dt.datetime = row[1]
            count: int = row[2]
            ranges.append(
                {
                    "date_from": _utc_z(bucket_start),
                    "date_to": _utc_z(bucket_end),
                    "count": count,
                }
            )

        return ranges

    def _dense_grid(self, ranges: list[dict]) -> _Grid:
        unit_seconds = 1 if self.query_date_range.interval_name == "second" else 60
        step = dt.timedelta(seconds=self.query_date_range.interval_count * unit_seconds)
        date_from, date_to = self.query_date_range.date_from(), self.query_date_range.date_to()
        epoch = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
        cursor = epoch + (date_from - epoch) // step * step
        counts = {bucket["date_from"]: bucket["count"] for bucket in ranges}
        starts: list[dt.datetime] = []
        while cursor < date_to:
            starts.append(cursor)
            cursor += step
        return _Grid(starts=starts, counts=[counts.get(utc_iso(start), 0) for start in starts], step=step)

    def _onset(self, ranges: list[dict]) -> dict | None:
        grid = self._dense_grid(ranges)
        starts, counts, step = grid.starts, grid.counts, grid.step
        partial = {0} if starts and starts[0] < self.query_date_range.date_from() else set()
        onset = find_onset(counts, partial)
        if onset is None:
            return None
        start = starts[onset.index]
        minutes = step.total_seconds() / 60
        if onset.confirmed:
            confidence = "high" if onset.baseline_samples >= ONSET_HIGH_CONFIDENCE_BASELINE else "medium"
        else:
            confidence = "low"
        return {
            "start": utc_iso(self._refined_start(start - step, start + step) or start),
            "end": utc_iso(starts[onset.end_index] + step) if onset.end_index is not None else None,
            "peak_at": utc_iso(starts[onset.peak_index]),
            "baseline_per_min": round(onset.expected / minutes, 1),
            "peak_per_min": round(counts[onset.peak_index] / minutes, 1),
            "confidence": confidence,
        }

    def _refined_start(self, date_from: dt.datetime, date_to: dt.datetime) -> dt.datetime | None:
        fine_range = DateRange(date_from=date_from.isoformat(), date_to=date_to.isoformat(), explicitDate=True)
        fine = CountRangesQueryRunner(
            team=self.team,
            query=self.query.model_copy(update={"dateRange": fine_range}),
            target_buckets=ONSET_FINE_TARGET_BUCKETS,
            limit_context=self.limit_context,
        )
        grid = fine._dense_grid(fine._ranges())
        starts, counts = grid.starts, grid.counts
        onset = find_onset(counts)
        return starts[onset.index] if onset is not None else None

    def _interval_short(self) -> str:
        unit = self.query_date_range.interval_name
        count = self.query_date_range.interval_count
        if unit == "second":
            return f"{count}s"
        if unit != "minute":
            raise ValueError(f"Unexpected interval unit from picker: {unit!r} (expected 'second' or 'minute')")
        # Normalise minute counts up to hours/days when cleanly divisible.
        if count and count % 1440 == 0:
            return f"{count // 1440}d"
        if count and count % 60 == 0:
            return f"{count // 60}h"
        return f"{count}m"

    def to_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
                SELECT
                    toStartOfInterval(timestamp, {one_interval_period}) AS bucket_start,
                    bucket_start + {one_interval_period} AS bucket_end,
                    count() AS event_count
                FROM logs
                WHERE {where}
                GROUP BY bucket_start
                ORDER BY bucket_start ASC
            """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "where": self.where_with_timestamp_bounds(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
