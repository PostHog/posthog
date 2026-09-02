import os
import re
import json
import datetime as dt
from datetime import UTC, datetime

import unittest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.filters import replace_filters
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.printer import prepare_and_print_ast

from posthog.clickhouse.client import sync_execute

from products.logs.backend.alert_check_query import (
    CHECKPOINT_MAX_STALENESS,
    AlertCheckCountResult,
    AlertCheckQuery,
    BatchedAlertCheckQuery,
    BatchedBucketedResult,
    BucketedCount,
    _rolling_check_ranges,
    fetch_live_logs_checkpoint,
    is_projection_eligible,
    resolve_alert_date_to,
)
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.temporal.constants import MAX_ALERT_COHORT_SIZE


def _seed_log_rows(
    team_id: int,
    service: str,
    base: datetime,
    counts_per_minute: list[int],
    uuid_prefix: str,
) -> None:
    rows = []
    for minute_idx, count in enumerate(counts_per_minute):
        minute_start = base + dt.timedelta(minutes=minute_idx)
        for log_idx in range(count):
            ts = minute_start + dt.timedelta(seconds=10 + log_idx)
            rows.append(
                _log_row(
                    team_id,
                    f"{uuid_prefix}-{minute_idx:03d}-{log_idx:03d}",
                    ts.strftime("%Y-%m-%d %H:%M:%S.%f"),
                    service,
                )
            )
    if rows:
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))


def _log_row(
    team_id: int,
    uuid: str,
    timestamp: str,
    service: str,
    *,
    severity: str = "info",
    attributes: dict[str, str] | None = None,
    body: str = "",
    resource_attributes: dict[str, str] | None = None,
) -> dict:
    return {
        "uuid": uuid,
        "team_id": team_id,
        "timestamp": timestamp,
        "body": body,
        "severity_text": severity,
        "severity_number": 9,
        "service_name": service,
        "resource_attributes": resource_attributes or {},
        "attributes_map_str": attributes or {},
    }


def _attribute_filters(
    key: str,
    value: str,
    *,
    services: list[str] | None = None,
    severities: list[str] | None = None,
) -> dict:
    filters: dict = {
        "filterGroup": {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [{"key": key, "value": value, "operator": "exact", "type": "log_attribute"}],
                }
            ],
        }
    }
    if services is not None:
        filters["serviceNames"] = services
    if severities is not None:
        filters["severityLevels"] = severities
    return filters


class TestIsProjectionEligible(unittest.TestCase):
    @parameterized.expand(
        [
            ("empty_filters", {}, True),
            ("service_only", {"serviceNames": ["argo-rollouts"]}, True),
            ("severity_only", {"severityLevels": ["error"]}, True),
            ("service_and_severity", {"serviceNames": ["argo-rollouts"], "severityLevels": ["error"]}, True),
            (
                "empty_filter_group",
                {"filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]}},
                True,
            ),
            (
                "body_filter_present",
                {
                    "filterGroup": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {"key": "message", "value": "error", "operator": "icontains", "type": "log"}
                                ],
                            }
                        ],
                    }
                },
                False,
            ),
            (
                "filter_group_is_list",
                {"filterGroup": [{"type": "AND", "values": []}]},
                False,
            ),
            (
                "filter_group_inner_value_not_dict",
                {"filterGroup": {"type": "AND", "values": ["not-a-dict"]}},
                False,
            ),
            (
                "attribute_filter_present",
                {
                    "filterGroup": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "logtag",
                                        "value": ["F"],
                                        "operator": "exact",
                                        "type": "log_attribute",
                                    }
                                ],
                            }
                        ],
                    }
                },
                False,
            ),
        ]
    )
    def test_projection_eligibility(self, _name, filters, expected):
        assert is_projection_eligible(filters) == expected


class TestAlertCheckQuery(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            rows = ""
            for line in f:
                log_item = json.loads(line)
                log_item["team_id"] = cls.team.id
                rows += json.dumps(log_item) + "\n"
            sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + rows)

    def _make_alert(self, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "Test Alert",
            "threshold_count": 10,
            "threshold_operator": "above",
            "window_minutes": 5,
            "filters": {},
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    def _make_query(self, alert: LogsAlertConfiguration) -> AlertCheckQuery:
        return AlertCheckQuery(
            team=self.team,
            alert=alert,
            date_from=datetime(2025, 12, 16, 9, 0, 0, tzinfo=UTC),
            date_to=datetime(2025, 12, 16, 10, 33, 0, tzinfo=UTC),
        )

    @freeze_time("2025-12-16T10:33:00Z")
    def test_projection_path_service_severity_only(self):
        alert = self._make_alert(
            filters={
                "serviceNames": ["argo-rollouts"],
                "severityLevels": ["info"],
            }
        )
        result = self._make_query(alert).execute()
        assert isinstance(result, AlertCheckCountResult)
        # argo-rollouts has 100 logs, some are info severity
        assert result.count > 0
        assert result.query_duration_ms >= 0

    @freeze_time("2025-12-16T10:33:00Z")
    def test_projection_path_service_only(self):
        alert = self._make_alert(
            filters={
                "serviceNames": ["billing"],
            }
        )
        result = self._make_query(alert).execute()
        assert isinstance(result, AlertCheckCountResult)
        assert result.count == 100

    @freeze_time("2025-12-16T10:33:00Z")
    def test_empty_filters_returns_all_logs(self):
        alert = self._make_alert(filters={})
        result = self._make_query(alert).execute()
        assert isinstance(result, AlertCheckCountResult)
        assert result.count > 0

    @freeze_time("2025-12-16T10:33:00Z")
    def test_null_filter_values_treated_as_empty(self):
        # The frontend/API can persist explicit `null` for these keys (as opposed to
        # omitting them), which previously crashed every check with a pydantic
        # ValidationError because `dict.get(key, default)` only falls back when the
        # key is absent, not when its value is None.
        alert = self._make_alert(filters={"serviceNames": None, "severityLevels": None})
        result = self._make_query(alert).execute()
        assert isinstance(result, AlertCheckCountResult)
        assert result.count > 0

    @freeze_time("2025-12-16T10:33:00Z")
    def test_raw_scan_path_body_filter(self):
        alert = self._make_alert(
            filters={
                "serviceNames": ["argo-rollouts"],
                "filterGroup": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "message",
                                    "value": "Argo Rollouts Dashboard",
                                    "operator": "icontains",
                                    "type": "log",
                                }
                            ],
                        }
                    ],
                },
            }
        )
        result = self._make_query(alert).execute()
        assert isinstance(result, AlertCheckCountResult)
        assert result.count > 0

    @freeze_time("2025-12-16T10:33:00Z")
    def test_raw_scan_path_resource_attribute_filter(self):
        alert = self._make_alert(
            filters={
                "filterGroup": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "k8s.container.name",
                                    "value": "argo-rollouts-dashboard",
                                    "operator": "icontains",
                                    "type": "log_resource_attribute",
                                }
                            ],
                        }
                    ],
                },
            }
        )
        result = self._make_query(alert).execute()
        assert isinstance(result, AlertCheckCountResult)
        assert result.count > 0

    @freeze_time("2025-12-16T10:33:00Z")
    def test_raw_scan_path_log_attribute_filter(self):
        # log_attribute filters read the `attributes_map_str` Map column. This only happens with
        # propertyGroupsMode=OPTIMIZED; without it the read falls back to JSONExtract, which is
        # illegal on a Map and the query errors at execution time.
        alert = self._make_alert(
            filters={
                "filterGroup": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "log.iostream",
                                    "value": "stderr",
                                    "operator": "exact",
                                    "type": "log_attribute",
                                }
                            ],
                        }
                    ],
                },
            }
        )
        result = self._make_query(alert).execute()
        assert isinstance(result, AlertCheckCountResult)
        assert result.count > 0

    @freeze_time("2025-12-16T10:33:00Z")
    def test_empty_results_return_zero(self):
        alert = self._make_alert(
            filters={
                "serviceNames": ["nonexistent-service"],
            }
        )
        result = self._make_query(alert).execute()
        assert isinstance(result, AlertCheckCountResult)
        assert result.count == 0

    @freeze_time("2025-12-16T10:33:00Z")
    def test_bucketed_output(self):
        alert = self._make_alert(
            filters={
                "serviceNames": ["argo-rollouts"],
            }
        )
        result = self._make_query(alert).execute_bucketed(interval_minutes=5)
        assert isinstance(result, list)
        assert len(result) > 0
        for item in result:
            assert isinstance(item, BucketedCount)
            assert item.count > 0
        # buckets should be sorted by timestamp
        timestamps = [item.timestamp for item in result]
        assert timestamps == sorted(timestamps)

    @freeze_time("2025-12-16T10:33:00Z")
    def test_bucketed_empty_results(self):
        alert = self._make_alert(
            filters={
                "serviceNames": ["nonexistent-service"],
            }
        )
        result = self._make_query(alert).execute_bucketed(interval_minutes=5)
        assert result == []

    @freeze_time("2025-12-16T10:33:00Z")
    def test_bucketed_output_with_body_filter(self):
        alert = self._make_alert(
            filters={
                "serviceNames": ["argo-rollouts"],
                "filterGroup": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "message",
                                    "value": "Argo Rollouts Dashboard",
                                    "operator": "icontains",
                                    "type": "log",
                                }
                            ],
                        }
                    ],
                },
            }
        )
        result = self._make_query(alert).execute_bucketed(interval_minutes=10)
        assert isinstance(result, list)
        total = sum(item.count for item in result)
        assert total > 0

    @freeze_time("2025-12-16T10:33:00Z")
    def test_bucketed_projection_path(self):
        alert = self._make_alert(
            filters={
                "serviceNames": ["argo-rollouts"],
                "severityLevels": ["info"],
            }
        )
        result = self._make_query(alert).execute_bucketed(interval_minutes=5)
        assert isinstance(result, list)
        assert len(result) > 0

    @freeze_time("2025-12-16T10:33:00Z")
    def test_bucketed_raw_scan_path(self):
        alert = self._make_alert(
            filters={
                "serviceNames": ["argo-rollouts"],
                "filterGroup": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "message",
                                    "value": "Argo Rollouts Dashboard",
                                    "operator": "icontains",
                                    "type": "log",
                                }
                            ],
                        }
                    ],
                },
            }
        )
        result = self._make_query(alert).execute_bucketed(interval_minutes=5)
        assert isinstance(result, list)
        assert len(result) > 0

    @freeze_time("2025-12-16T10:33:00Z")
    def test_bucketed_count_placement(self):
        # Seeds five logs at known timestamps spanning two 5-min buckets
        # ([10:00, 10:05) and [10:05, 10:10)) and asserts the per-bucket counts
        # are placed correctly. Catches timezone / boundary off-by-one bugs that
        # would shift counts by one bucket while preserving the total.
        rows = [
            {
                "uuid": f"{i}",
                "team_id": self.team.id,
                "timestamp": ts,
                "body": "",
                "severity_text": "info",
                "severity_number": 9,
                "service_name": "bucket_placement_test",
                "resource_attributes": {},
                "attributes_map_str": {},
            }
            for i, ts in enumerate(
                [
                    "2025-12-16 10:00:30",  # bucket [10:00, 10:05)
                    "2025-12-16 10:01:00",  # bucket [10:00, 10:05)
                    "2025-12-16 10:04:59",  # bucket [10:00, 10:05)
                    "2025-12-16 10:05:00",  # bucket [10:05, 10:10)
                    "2025-12-16 10:09:59",  # bucket [10:05, 10:10)
                ]
            )
        ]
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

        alert = self._make_alert(filters={"serviceNames": ["bucket_placement_test"]})
        result = AlertCheckQuery(
            team=self.team,
            alert=alert,
            date_from=datetime(2025, 12, 16, 10, 0, 0, tzinfo=UTC),
            date_to=datetime(2025, 12, 16, 10, 10, 0, tzinfo=UTC),
        ).execute_bucketed(interval_minutes=5)

        assert len(result) == 2
        bucket_a, bucket_b = result
        assert bucket_a.count == 3
        assert bucket_b.count == 2
        # Bucket boundary alignment: starts of [10:00, 10:05) and [10:05, 10:10)
        assert bucket_a.timestamp.replace(tzinfo=UTC) == datetime(2025, 12, 16, 10, 0, 0, tzinfo=UTC)
        assert bucket_b.timestamp.replace(tzinfo=UTC) == datetime(2025, 12, 16, 10, 5, 0, tzinfo=UTC)

    @freeze_time("2025-12-16T10:33:00Z")
    def test_bucketed_sum_equals_single_count(self):
        # Same WHERE clause, same date range, just GROUP BY in one path. If any
        # rows fall through bucket boundaries (e.g. a half-open interval bug
        # in toStartOfInterval), the sum would diverge from the single count.
        alert = self._make_alert(filters={"serviceNames": ["argo-rollouts"]})
        query = self._make_query(alert)

        single = query.execute()
        bucketed = query.execute_bucketed(interval_minutes=5)

        assert sum(b.count for b in bucketed) == single.count

    @freeze_time("2025-12-16T11:00:00Z")
    def test_bucketed_count_matches_python_histogram_across_random_inputs(self):
        # Stress test the actual ClickHouse bucketing: seed N logs at random
        # timestamps with a unique service name, run execute_bucketed, then
        # bucket the same timestamps in python and assert per-bucket equality.
        # Catches: bucket alignment math, half-open boundary handling, sub-second
        # bucketing, edge cases at hour/minute crossings.
        import random as _random

        rng = _random.Random(42)  # deterministic seed; trial output reproducible
        base = datetime(2025, 12, 16, 9, 0, 0, tzinfo=UTC)
        range_seconds = 2 * 3600  # 2-hour window covering hour boundary

        # Generate all trials' inputs upfront, then batch-INSERT all rows in one
        # CH round-trip. Service-name uniqueness keeps trials isolated at query time.
        trials = []
        all_rows: list[dict] = []
        for trial in range(15):
            n_logs = rng.randint(5, 200)
            offsets_seconds = [rng.randint(0, range_seconds - 1) for _ in range(n_logs)]
            bucket_minutes = rng.choice([1, 5, 10, 15, 30])
            service_name = f"hist_stress_test_{trial}"
            trials.append((service_name, offsets_seconds, bucket_minutes))
            all_rows.extend(
                {
                    "uuid": f"hist-{trial}-{i}",
                    "team_id": self.team.id,
                    "timestamp": (base + dt.timedelta(seconds=off)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                    "body": "",
                    "severity_text": "info",
                    "severity_number": 9,
                    "service_name": service_name,
                    "resource_attributes": {},
                    "attributes_map_str": {},
                }
                for i, off in enumerate(offsets_seconds)
            )
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in all_rows))

        for service_name, offsets_seconds, bucket_minutes in trials:
            alert = self._make_alert(filters={"serviceNames": [service_name]})
            result = AlertCheckQuery(
                team=self.team,
                alert=alert,
                date_from=base,
                date_to=base + dt.timedelta(seconds=range_seconds),
            ).execute_bucketed(interval_minutes=bucket_minutes, limit=10_000)

            expected: dict[datetime, int] = {}
            for off in offsets_seconds:
                ts = base + dt.timedelta(seconds=off)
                total_minutes = ts.hour * 60 + ts.minute
                floored = (total_minutes // bucket_minutes) * bucket_minutes
                bucket_key = ts.replace(hour=floored // 60, minute=floored % 60, second=0, microsecond=0)
                expected[bucket_key] = expected.get(bucket_key, 0) + 1

            actual = {
                (b.timestamp.replace(tzinfo=UTC) if b.timestamp.tzinfo is None else b.timestamp): b.count
                for b in result
            }
            assert actual == expected, (
                f"service={service_name} n_logs={len(offsets_seconds)} bucket_minutes={bucket_minutes}\n"
                f"actual:   {sorted(actual.items())}\n"
                f"expected: {sorted(expected.items())}"
            )

    @freeze_time("2025-12-17T01:00:00Z")
    def test_bucketed_count_correct_across_midnight_boundary(self):
        # Cadence-grid bucketing anchors at midnight UTC — buckets that span
        # the day rollover must land in the right slot.
        rows = [
            {
                "uuid": f"mid-{i}",
                "team_id": self.team.id,
                "timestamp": ts,
                "body": "",
                "severity_text": "info",
                "severity_number": 9,
                "service_name": "midnight_test",
                "resource_attributes": {},
                "attributes_map_str": {},
            }
            for i, ts in enumerate(
                [
                    "2025-12-16 23:55:00.000000",  # bucket [23:55, 24:00)
                    "2025-12-16 23:59:59.999999",  # bucket [23:55, 24:00)
                    "2025-12-17 00:00:00.000000",  # bucket [00:00, 00:05)
                    "2025-12-17 00:04:59.999999",  # bucket [00:00, 00:05)
                    "2025-12-17 00:05:00.000000",  # bucket [00:05, 00:10)
                ]
            )
        ]
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

        alert = self._make_alert(filters={"serviceNames": ["midnight_test"]})
        result = AlertCheckQuery(
            team=self.team,
            alert=alert,
            date_from=datetime(2025, 12, 16, 23, 50, 0, tzinfo=UTC),
            date_to=datetime(2025, 12, 17, 0, 10, 0, tzinfo=UTC),
        ).execute_bucketed(interval_minutes=5)

        actual = {b.timestamp.replace(tzinfo=UTC): b.count for b in result}
        expected = {
            datetime(2025, 12, 16, 23, 55, 0, tzinfo=UTC): 2,
            datetime(2025, 12, 17, 0, 0, 0, tzinfo=UTC): 2,
            datetime(2025, 12, 17, 0, 5, 0, tzinfo=UTC): 1,
        }
        assert actual == expected

    @freeze_time("2025-12-16T10:33:00Z")
    def test_bucketed_subsecond_precision_at_boundaries(self):
        # DateTime64(6) precision: a log at :04:59.999999 is in [10:00, 10:05);
        # one at :05:00.000000 is in [10:05, 10:10). Boundary ownership matters
        # because rounding errors here would silently mis-bucket logs.
        rows = [
            {
                "uuid": f"sub-{i}",
                "team_id": self.team.id,
                "timestamp": ts,
                "body": "",
                "severity_text": "info",
                "severity_number": 9,
                "service_name": "subsecond_test",
                "resource_attributes": {},
                "attributes_map_str": {},
            }
            for i, ts in enumerate(
                [
                    "2025-12-16 10:04:59.999999",  # bucket [10:00, 10:05)
                    "2025-12-16 10:05:00.000000",  # bucket [10:05, 10:10)
                    "2025-12-16 10:05:00.000001",  # bucket [10:05, 10:10)
                ]
            )
        ]
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

        alert = self._make_alert(filters={"serviceNames": ["subsecond_test"]})
        result = AlertCheckQuery(
            team=self.team,
            alert=alert,
            date_from=datetime(2025, 12, 16, 10, 0, 0, tzinfo=UTC),
            date_to=datetime(2025, 12, 16, 10, 10, 0, tzinfo=UTC),
        ).execute_bucketed(interval_minutes=5)

        actual = {b.timestamp.replace(tzinfo=UTC): b.count for b in result}
        expected = {
            datetime(2025, 12, 16, 10, 0, 0, tzinfo=UTC): 1,
            datetime(2025, 12, 16, 10, 5, 0, tzinfo=UTC): 2,
        }
        assert actual == expected

    @freeze_time("2025-12-16T10:33:00Z")
    def test_bucketed_excludes_log_at_exact_date_to(self):
        # Half-open [date_from, date_to) — a log timestamped exactly at date_to
        # must be excluded. Catches an off-by-one if anyone changes < to <=.
        rows = [
            {
                "uuid": f"bnd-{i}",
                "team_id": self.team.id,
                "timestamp": ts,
                "body": "",
                "severity_text": "info",
                "severity_number": 9,
                "service_name": "boundary_test",
                "resource_attributes": {},
                "attributes_map_str": {},
            }
            for i, ts in enumerate(
                [
                    "2025-12-16 10:09:59.999999",  # included
                    "2025-12-16 10:10:00.000000",  # exactly date_to → excluded
                ]
            )
        ]
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

        alert = self._make_alert(filters={"serviceNames": ["boundary_test"]})
        result = AlertCheckQuery(
            team=self.team,
            alert=alert,
            date_from=datetime(2025, 12, 16, 10, 0, 0, tzinfo=UTC),
            date_to=datetime(2025, 12, 16, 10, 10, 0, tzinfo=UTC),
        ).execute_bucketed(interval_minutes=5)

        actual = {b.timestamp.replace(tzinfo=UTC): b.count for b in result}
        # Only the .999999 log should be counted; the .000000 log is at date_to and excluded.
        assert actual == {datetime(2025, 12, 16, 10, 5, 0, tzinfo=UTC): 1}

    @freeze_time("2025-12-16T10:33:00Z")
    def test_bucketed_sparse_data_returns_only_populated_buckets(self):
        # CH GROUP BY only emits buckets that have data. This is the contract
        # downstream callers (the activity, the simulate fill helper) depend on:
        # if you query 50 minutes of data and only 3 buckets have logs, you get
        # 3 BucketedCount rows back, not 10.
        rows = [
            {
                "uuid": f"sparse-{i}",
                "team_id": self.team.id,
                "timestamp": ts,
                "body": "",
                "severity_text": "info",
                "severity_number": 9,
                "service_name": "sparse_test",
                "resource_attributes": {},
                "attributes_map_str": {},
            }
            for i, ts in enumerate(
                [
                    "2025-12-16 09:00:00.000000",  # bucket [09:00, 09:05)
                    "2025-12-16 09:25:00.000000",  # bucket [09:25, 09:30)
                    "2025-12-16 09:45:00.000000",  # bucket [09:45, 09:50)
                ]
            )
        ]
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

        alert = self._make_alert(filters={"serviceNames": ["sparse_test"]})
        result = AlertCheckQuery(
            team=self.team,
            alert=alert,
            date_from=datetime(2025, 12, 16, 9, 0, 0, tzinfo=UTC),
            date_to=datetime(2025, 12, 16, 9, 50, 0, tzinfo=UTC),
        ).execute_bucketed(interval_minutes=5)

        # Only 3 populated buckets returned, not 10. Each has count=1.
        assert len(result) == 3
        assert [b.count for b in result] == [1, 1, 1]
        assert [b.timestamp.replace(tzinfo=UTC) for b in result] == [
            datetime(2025, 12, 16, 9, 0, 0, tzinfo=UTC),
            datetime(2025, 12, 16, 9, 25, 0, tzinfo=UTC),
            datetime(2025, 12, 16, 9, 45, 0, tzinfo=UTC),
        ]

    def test_team_mismatch_raises(self):
        from posthog.models import Organization, Team

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        alert = self._make_alert()

        with self.assertRaisesRegex(ValueError, f"belongs to team {self.team.id}, not {other_team.id}"):
            AlertCheckQuery(
                team=other_team,
                alert=alert,
                date_from=datetime(2025, 12, 16, 9, 0, 0, tzinfo=UTC),
                date_to=datetime(2025, 12, 16, 10, 33, 0, tzinfo=UTC),
            )

    def test_timeout_propagates(self):
        alert = self._make_alert(filters={"serviceNames": ["argo-rollouts"]})
        query = self._make_query(alert)
        with patch(
            "products.logs.backend.alert_check_query.execute_hogql_query",
            side_effect=Exception("ClickHouse timeout"),
        ):
            with self.assertRaisesRegex(Exception, "ClickHouse timeout"):
                query.execute()


class TestEvaluatorWindowAccuracy(ClickhouseTestMixin, APIBaseTest):
    """`execute_periods` counts must be invariant to `next_check_at` clock offset."""

    def _make_alert(self, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "Window accuracy test",
            "threshold_count": 10,
            "threshold_operator": "above",
            "window_minutes": 60,
            "filters": {"serviceNames": ["window_accuracy_test"]},
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    def _seed_one_log_per_minute(self, start_hour_utc: int, hours: int = 3) -> None:
        rows = []
        for h in range(hours):
            for m in range(60):
                rows.append(
                    {
                        "uuid": f"window-{h:02d}-{m:02d}",
                        "team_id": self.team.id,
                        "timestamp": f"2025-12-16 {start_hour_utc + h:02d}:{m:02d}:00",
                        "body": "",
                        "severity_text": "info",
                        "severity_number": 9,
                        "service_name": "window_accuracy_test",
                        "resource_attributes": {},
                        "attributes_map_str": {},
                    }
                )
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

    @parameterized.expand(
        [
            ("offset_0_clock_aligned", 0),
            ("offset_5", 5),
            ("offset_10", 10),
            ("offset_15", 15),
            ("offset_20", 20),
            ("offset_30", 30),
            ("offset_45", 45),
            ("offset_55", 55),
        ]
    )
    @freeze_time("2025-12-16T13:30:00Z")
    def test_m_equals_1_full_window_count_is_independent_of_nca_offset(self, _name: str, offset_minutes: int):
        # 1 log/min × 60-min window = 60.
        self._seed_one_log_per_minute(start_hour_utc=10, hours=3)
        alert = self._make_alert(window_minutes=60, evaluation_periods=1)

        nca = datetime(2025, 12, 16, 12, 0, tzinfo=UTC) + dt.timedelta(minutes=offset_minutes)
        date_from = nca - dt.timedelta(minutes=alert.window_minutes * alert.evaluation_periods)

        result = AlertCheckQuery(team=self.team, alert=alert, date_from=date_from, date_to=nca).execute_periods(
            period_minutes=alert.window_minutes, period_count=alert.evaluation_periods
        )

        assert len(result) == 1
        assert result[0].count == 60, (
            f"NCA {nca.time()}: window [{date_from.time()}, {nca.time()}) has 60 logs by construction; "
            f"got {result[0].count}"
        )

    @parameterized.expand(
        [
            ("offset_0_clock_aligned", 0),
            ("offset_5", 5),
            ("offset_10", 10),
            ("offset_25", 25),
            ("offset_55", 55),
        ]
    )
    @freeze_time("2025-12-16T13:30:00Z")
    def test_m_of_n_each_period_reports_full_window_count(self, _name: str, offset_minutes: int):
        # 1 log/min × 3 × 20-min periods = 20 each.
        self._seed_one_log_per_minute(start_hour_utc=10, hours=3)
        alert = self._make_alert(window_minutes=20, evaluation_periods=3)

        nca = datetime(2025, 12, 16, 12, 0, tzinfo=UTC) + dt.timedelta(minutes=offset_minutes)
        date_from = nca - dt.timedelta(minutes=alert.window_minutes * alert.evaluation_periods)

        result = AlertCheckQuery(team=self.team, alert=alert, date_from=date_from, date_to=nca).execute_periods(
            period_minutes=alert.window_minutes, period_count=alert.evaluation_periods
        )

        assert len(result) == 3
        # Every period must contain exactly 20 logs (1/min × 20 min).
        for i, period in enumerate(result):
            assert period.count == 20, (
                f"Period {i} (offset {offset_minutes}min) at {period.timestamp.time()} should have 20 logs; "
                f"got {period.count}. Per-period counts: {[p.count for p in result]}"
            )
        # Total across all periods = 60 logs.
        assert sum(p.count for p in result) == 60

    @freeze_time("2025-12-16T13:30:00Z")
    def test_m_equals_1_steady_rate_does_not_oscillate_across_hour(self):
        self._seed_one_log_per_minute(start_hour_utc=10, hours=3)
        alert = self._make_alert(window_minutes=60, evaluation_periods=1)

        counts_by_offset = {}
        for offset in (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55):
            nca = datetime(2025, 12, 16, 12, 0, tzinfo=UTC) + dt.timedelta(minutes=offset)
            result = AlertCheckQuery(
                team=self.team, alert=alert, date_from=nca - dt.timedelta(minutes=60), date_to=nca
            ).execute_periods(period_minutes=60, period_count=1)
            counts_by_offset[offset] = result[0].count

        unique_counts = set(counts_by_offset.values())
        assert unique_counts == {60}, (
            f"Reported counts vary across NCA offsets within the same hour, despite constant log rate. "
            f"Per-offset counts: {counts_by_offset}"
        )

    @freeze_time("2025-12-16T13:30:00Z")
    def test_m_of_n_steady_rate_does_not_oscillate_across_hour(self):
        self._seed_one_log_per_minute(start_hour_utc=10, hours=3)
        alert = self._make_alert(window_minutes=20, evaluation_periods=3)

        for offset in (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55):
            nca = datetime(2025, 12, 16, 12, 0, tzinfo=UTC) + dt.timedelta(minutes=offset)
            result = AlertCheckQuery(
                team=self.team, alert=alert, date_from=nca - dt.timedelta(minutes=60), date_to=nca
            ).execute_periods(period_minutes=20, period_count=3)
            counts = [p.count for p in result]
            assert counts == [20, 20, 20], (
                f"NCA offset {offset}min: M-of-N period counts diverge from constant 20/period; got {counts}"
            )


class TestExecuteRollingChecks(ClickhouseTestMixin, APIBaseTest):
    SERVICE = "rolling_checks_test"

    def _make_alert(self, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "Rolling check test",
            "threshold_count": 10,
            "threshold_operator": "above",
            "window_minutes": 15,
            "filters": {"serviceNames": [self.SERVICE]},
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    def _seed_per_minute(self, base: datetime, counts_per_minute: list[int]) -> None:
        _seed_log_rows(self.team.id, self.SERVICE, base, counts_per_minute, "rc")

    @freeze_time("2025-12-16T13:30:00Z")
    def test_m_equals_1_returns_single_latest_window_count(self):
        self._seed_per_minute(datetime(2025, 12, 16, 12, 0, tzinfo=UTC), [1, 1, 1, 1, 1])
        alert = self._make_alert(window_minutes=15)
        nca = datetime(2025, 12, 16, 12, 15, tzinfo=UTC)

        result = AlertCheckQuery(
            team=self.team, alert=alert, date_from=nca - dt.timedelta(minutes=15), date_to=nca
        ).execute_rolling_checks(nca=nca, window_minutes=15, cadence_minutes=5, period_count=1)

        assert len(result) == 1
        assert result[0].count == 5
        assert result[0].timestamp == datetime(2025, 12, 16, 12, 0, tzinfo=UTC)

    @freeze_time("2025-12-16T13:30:00Z")
    def test_m_equals_3_overlapping_windows_each_count_includes_shared_data(self):
        self._seed_per_minute(datetime(2025, 12, 16, 12, 0, tzinfo=UTC), [1] * 60)
        alert = self._make_alert(window_minutes=15)
        nca = datetime(2025, 12, 16, 12, 30, tzinfo=UTC)
        date_from = nca - dt.timedelta(minutes=15 + 2 * 5)

        result = AlertCheckQuery(team=self.team, alert=alert, date_from=date_from, date_to=nca).execute_rolling_checks(
            nca=nca, window_minutes=15, cadence_minutes=5, period_count=3
        )

        assert len(result) == 3
        assert [b.count for b in result] == [15, 15, 15]
        assert [b.timestamp for b in result] == [
            datetime(2025, 12, 16, 12, 5, tzinfo=UTC),
            datetime(2025, 12, 16, 12, 10, tzinfo=UTC),
            datetime(2025, 12, 16, 12, 15, tzinfo=UTC),
        ]

    @freeze_time("2025-12-16T13:30:00Z")
    def test_spike_is_visible_in_all_windows_that_contain_it(self):
        counts = [0] * 60
        for m in range(8, 13):
            counts[m] = 40
        self._seed_per_minute(datetime(2025, 12, 16, 12, 0, tzinfo=UTC), counts)
        alert = self._make_alert(window_minutes=15)
        nca = datetime(2025, 12, 16, 12, 30, tzinfo=UTC)
        date_from = nca - dt.timedelta(minutes=15 + 4 * 5)

        result = AlertCheckQuery(team=self.team, alert=alert, date_from=date_from, date_to=nca).execute_rolling_checks(
            nca=nca, window_minutes=15, cadence_minutes=5, period_count=5
        )

        assert [b.count for b in result] == [80, 200, 200, 120, 0]

    @parameterized.expand(
        [
            ("offset_0", 0),
            ("offset_1", 1),
            ("offset_5", 5),
            ("offset_7", 7),
            ("offset_13", 13),
            ("offset_17", 17),
            ("offset_22", 22),
            ("offset_30", 30),
            ("offset_47", 47),
            ("offset_55", 55),
            ("offset_59", 59),
        ]
    )
    @freeze_time("2025-12-16T13:30:00Z")
    def test_count_is_invariant_to_nca_clock_offset(self, _name: str, offset_min: int):
        self._seed_per_minute(datetime(2025, 12, 16, 10, 0, tzinfo=UTC), [1] * 180)
        alert = self._make_alert(window_minutes=15)

        nca = datetime(2025, 12, 16, 12, 0, tzinfo=UTC) + dt.timedelta(minutes=offset_min)
        date_from = nca - dt.timedelta(minutes=15 + 2 * 5)
        result = AlertCheckQuery(team=self.team, alert=alert, date_from=date_from, date_to=nca).execute_rolling_checks(
            nca=nca, window_minutes=15, cadence_minutes=5, period_count=3
        )
        counts = [b.count for b in result]
        assert counts == [15, 15, 15]

    @freeze_time("2025-12-16T13:30:00Z")
    def test_cadence_other_than_5min_works(self):
        self._seed_per_minute(datetime(2025, 12, 16, 12, 0, tzinfo=UTC), [1] * 60)
        alert = self._make_alert(window_minutes=15, check_interval_minutes=10)
        nca = datetime(2025, 12, 16, 12, 40, tzinfo=UTC)
        date_from = nca - dt.timedelta(minutes=35)

        result = AlertCheckQuery(team=self.team, alert=alert, date_from=date_from, date_to=nca).execute_rolling_checks(
            nca=nca, window_minutes=15, cadence_minutes=10, period_count=3
        )

        assert [b.count for b in result] == [15, 15, 15]

    @freeze_time("2025-12-16T13:30:00Z")
    def test_empty_results_returns_zero_for_each_period(self):
        alert = self._make_alert(filters={"serviceNames": ["nonexistent"]})
        nca = datetime(2025, 12, 16, 12, 30, tzinfo=UTC)
        date_from = nca - dt.timedelta(minutes=15 + 2 * 5)

        result = AlertCheckQuery(team=self.team, alert=alert, date_from=date_from, date_to=nca).execute_rolling_checks(
            nca=nca, window_minutes=15, cadence_minutes=5, period_count=3
        )

        assert len(result) == 3
        assert [b.count for b in result] == [0, 0, 0]


class TestExecuteRollingChecksBatched(ClickhouseTestMixin, APIBaseTest):
    SERVICE_A = "rolling_batch_a"
    SERVICE_B = "rolling_batch_b"

    def _make_alert(self, *, filters: dict, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "Rolling batch test",
            "threshold_count": 10,
            "threshold_operator": "above",
            "window_minutes": 15,
            "filters": filters,
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    def _seed(self, service: str, base: datetime, counts_per_minute: list[int]) -> None:
        _seed_log_rows(self.team.id, service, base, counts_per_minute, f"rcb-{service}")

    @freeze_time("2025-12-16T13:30:00Z")
    def test_per_alert_counts_match_single_alert_query(self):
        base = datetime(2025, 12, 16, 12, 0, tzinfo=UTC)
        self._seed(self.SERVICE_A, base, [3] * 60)
        self._seed(self.SERVICE_B, base, [7] * 60)

        alert_a = self._make_alert(filters={"serviceNames": [self.SERVICE_A]})
        alert_b = self._make_alert(filters={"serviceNames": [self.SERVICE_B]})

        nca = datetime(2025, 12, 16, 12, 30, tzinfo=UTC)
        date_from = nca - dt.timedelta(minutes=15 + 2 * 5)

        batched = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert_a, alert_b], date_from=date_from, date_to=nca
        ).execute_rolling_checks(nca=nca, window_minutes=15, cadence_minutes=5, period_count=3)

        for alert in (alert_a, alert_b):
            single = AlertCheckQuery(
                team=self.team, alert=alert, date_from=date_from, date_to=nca
            ).execute_rolling_checks(nca=nca, window_minutes=15, cadence_minutes=5, period_count=3)
            assert batched.per_alert[str(alert.id)] == single

    @freeze_time("2025-12-16T13:30:00Z")
    def test_single_alert_cohort_matches_per_alert_path(self):
        base = datetime(2025, 12, 16, 12, 0, tzinfo=UTC)
        self._seed(self.SERVICE_A, base, [5] * 60)
        alert = self._make_alert(filters={"serviceNames": [self.SERVICE_A]})

        nca = datetime(2025, 12, 16, 12, 30, tzinfo=UTC)
        date_from = nca - dt.timedelta(minutes=15 + 2 * 5)

        batched = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert], date_from=date_from, date_to=nca
        ).execute_rolling_checks(nca=nca, window_minutes=15, cadence_minutes=5, period_count=3)
        single = AlertCheckQuery(team=self.team, alert=alert, date_from=date_from, date_to=nca).execute_rolling_checks(
            nca=nca, window_minutes=15, cadence_minutes=5, period_count=3
        )

        assert batched.per_alert[str(alert.id)] == single

    @freeze_time("2025-12-16T13:30:00Z")
    def test_m_equals_1_returns_single_period_per_alert(self):
        base = datetime(2025, 12, 16, 12, 0, tzinfo=UTC)
        self._seed(self.SERVICE_A, base, [2] * 60)
        alert = self._make_alert(filters={"serviceNames": [self.SERVICE_A]})

        nca = datetime(2025, 12, 16, 12, 30, tzinfo=UTC)
        date_from = nca - dt.timedelta(minutes=15)

        result = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert], date_from=date_from, date_to=nca
        ).execute_rolling_checks(nca=nca, window_minutes=15, cadence_minutes=5, period_count=1)

        per = result.per_alert[str(alert.id)]
        assert len(per) == 1
        assert per[0].count == 30


class TestBatchedAlertCheckQuery(ClickhouseTestMixin, APIBaseTest):
    """Per-team batching: run N alerts in one CH query via `countIf(<predicate>)`.

    Equivalence assertion is the heart of the test surface — for every alert in
    a batch, the per-alert column from the batched query must match what the
    single-alert `AlertCheckQuery.execute_bucketed` returns against the same
    window. Anything else and we silently break alert correctness.
    """

    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            rows = ""
            for line in f:
                log_item = json.loads(line)
                log_item["team_id"] = cls.team.id
                rows += json.dumps(log_item) + "\n"
            sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + rows)

    def _make_alert(self, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "Test Alert",
            "threshold_count": 10,
            "threshold_operator": "above",
            "window_minutes": 5,
            "filters": {},
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    def _date_range(self) -> tuple[datetime, datetime]:
        return datetime(2025, 12, 16, 9, 0, 0, tzinfo=UTC), datetime(2025, 12, 16, 10, 33, 0, tzinfo=UTC)

    @freeze_time("2025-12-16T10:33:00Z")
    def test_returns_per_alert_buckets(self):
        alert_a = self._make_alert(name="A", filters={"serviceNames": ["argo-rollouts"]})
        alert_b = self._make_alert(name="B", filters={"serviceNames": ["billing"]})
        date_from, date_to = self._date_range()

        result = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert_a, alert_b], date_from=date_from, date_to=date_to
        ).execute_bucketed(interval_minutes=5)

        assert isinstance(result, BatchedBucketedResult)
        assert set(result.per_alert.keys()) == {str(alert_a.id), str(alert_b.id)}
        assert result.query_duration_ms >= 0

    @freeze_time("2025-12-16T10:33:00Z")
    def test_per_alert_counts_match_single_alert_query(self):
        # Equivalence guarantee: every per-alert bucket column from the batched
        # query must match what a single-alert AlertCheckQuery returns. If they
        # diverge, alert correctness silently breaks for every batched alert.
        alert_a = self._make_alert(name="A", filters={"serviceNames": ["argo-rollouts"]})
        alert_b = self._make_alert(name="B", filters={"serviceNames": ["billing"], "severityLevels": ["info"]})
        date_from, date_to = self._date_range()

        batched = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert_a, alert_b], date_from=date_from, date_to=date_to
        ).execute_bucketed(interval_minutes=5)

        for alert in (alert_a, alert_b):
            single = AlertCheckQuery(
                team=self.team, alert=alert, date_from=date_from, date_to=date_to
            ).execute_bucketed(interval_minutes=5)
            batched_for_alert = batched.per_alert[str(alert.id)]

            # Batched returns a row per cohort bucket (every bucket the team has data
            # in), with count=0 entries for buckets where this alert's predicate
            # didn't match. Single-alert only emits buckets where the alert matched.
            # So filter the batched view to the same set before comparing.
            non_zero_batched = [b for b in batched_for_alert if b.count > 0]
            assert non_zero_batched == single, f"alert={alert.name}"

    @freeze_time("2025-12-16T10:33:00Z")
    def test_single_alert_cohort_is_supported(self):
        # The activity sends every cohort through the batched path even when
        # there's only one alert in it. Verify N=1 behaves correctly.
        alert = self._make_alert(filters={"serviceNames": ["argo-rollouts"]})
        date_from, date_to = self._date_range()

        result = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert], date_from=date_from, date_to=date_to
        ).execute_bucketed(interval_minutes=5)

        assert list(result.per_alert.keys()) == [str(alert.id)]
        non_zero = [b for b in result.per_alert[str(alert.id)] if b.count > 0]
        assert len(non_zero) > 0

    @freeze_time("2025-12-16T10:33:00Z")
    def test_empty_alerts_raises(self):
        date_from, date_to = self._date_range()
        with self.assertRaisesRegex(ValueError, "at least one alert"):
            BatchedAlertCheckQuery(team=self.team, alerts=[], date_from=date_from, date_to=date_to)

    def test_team_mismatch_raises(self):
        from posthog.models import Organization, Team

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        alert = self._make_alert()

        with self.assertRaisesRegex(ValueError, "All alerts in a batch must belong to the same team"):
            BatchedAlertCheckQuery(
                team=other_team,
                alerts=[alert],
                date_from=datetime(2025, 12, 16, 9, 0, 0, tzinfo=UTC),
                date_to=datetime(2025, 12, 16, 10, 33, 0, tzinfo=UTC),
            )

    @freeze_time("2025-12-16T10:33:00Z")
    def test_mixed_projection_eligibility_drops_to_raw_scan(self):
        # If any alert in the batch has a body filter, the cohort drops projection
        # eligibility — entire batch falls back to raw scan. Both columns still
        # produce correct counts; this test just verifies the query runs.
        alert_proj = self._make_alert(name="P", filters={"serviceNames": ["argo-rollouts"]})
        alert_body = self._make_alert(
            name="B",
            filters={
                "serviceNames": ["argo-rollouts"],
                "filterGroup": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "message",
                                    "value": "Argo Rollouts Dashboard",
                                    "operator": "icontains",
                                    "type": "log",
                                }
                            ],
                        }
                    ],
                },
            },
        )
        date_from, date_to = self._date_range()

        result = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert_proj, alert_body], date_from=date_from, date_to=date_to
        ).execute_bucketed(interval_minutes=5)

        assert set(result.per_alert.keys()) == {str(alert_proj.id), str(alert_body.id)}

    @freeze_time("2025-12-16T10:33:00Z")
    def test_no_matching_logs_returns_zero_counts(self):
        alert_a = self._make_alert(name="A", filters={"serviceNames": ["nonexistent-a"]})
        alert_b = self._make_alert(name="B", filters={"serviceNames": ["nonexistent-b"]})
        date_from, date_to = self._date_range()

        result = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert_a, alert_b], date_from=date_from, date_to=date_to
        ).execute_bucketed(interval_minutes=5)

        # When no alert has matching logs, the team scan still emits buckets for
        # rows that exist in the window — but all per-alert columns are 0. If the
        # team has no logs at all in the window, we get an empty per_alert list.
        for alert in (alert_a, alert_b):
            buckets = result.per_alert[str(alert.id)]
            assert all(b.count == 0 for b in buckets)

    @freeze_time("2025-12-16T10:33:00Z")
    def test_buckets_in_ascending_order(self):
        alert_a = self._make_alert(name="A", filters={"serviceNames": ["argo-rollouts"]})
        alert_b = self._make_alert(name="B", filters={"serviceNames": ["billing"]})
        date_from, date_to = self._date_range()

        result = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert_a, alert_b], date_from=date_from, date_to=date_to
        ).execute_bucketed(interval_minutes=5)

        for alert in (alert_a, alert_b):
            timestamps = [b.timestamp for b in result.per_alert[str(alert.id)]]
            assert timestamps == sorted(timestamps), f"alert={alert.name}"

    @freeze_time("2025-12-16T10:33:00Z")
    def test_query_failure_propagates(self):
        alert = self._make_alert()
        date_from, date_to = self._date_range()
        query = BatchedAlertCheckQuery(team=self.team, alerts=[alert], date_from=date_from, date_to=date_to)
        with patch(
            "products.logs.backend.alert_check_query.execute_hogql_query",
            side_effect=Exception("ClickHouse timeout"),
        ):
            with self.assertRaisesRegex(Exception, "ClickHouse timeout"):
                query.execute_bucketed(interval_minutes=5)

    @parameterized.expand(
        [
            ("offset_0_clock_aligned", 0),
            ("offset_5", 5),
            ("offset_25", 25),
            ("offset_55", 55),
        ]
    )
    @freeze_time("2025-12-16T13:30:00Z")
    def test_execute_periods_per_alert_per_period_indexing_is_correct(self, _name: str, offset_minutes: int):
        # service_a: 1 log/min. service_b: 2 logs/min. Expected: A=[20,20,20], B=[40,40,40] for any NCA offset.
        rows = []
        for h in range(3):
            for m in range(60):
                # service_a: 1 log/min. service_b: 2 logs/min (a 'left' and a 'right' variant).
                rows.append(
                    {
                        "uuid": f"a-{h:02d}-{m:02d}",
                        "team_id": self.team.id,
                        "timestamp": f"2025-12-16 {11 + h:02d}:{m:02d}:00",
                        "body": "",
                        "severity_text": "info",
                        "severity_number": 9,
                        "service_name": "batched_window_a",
                        "resource_attributes": {},
                        "attributes_map_str": {},
                    }
                )
                rows.append(
                    {
                        "uuid": f"b1-{h:02d}-{m:02d}",
                        "team_id": self.team.id,
                        "timestamp": f"2025-12-16 {11 + h:02d}:{m:02d}:10",
                        "body": "",
                        "severity_text": "info",
                        "severity_number": 9,
                        "service_name": "batched_window_b",
                        "resource_attributes": {},
                        "attributes_map_str": {},
                    }
                )
                rows.append(
                    {
                        "uuid": f"b2-{h:02d}-{m:02d}",
                        "team_id": self.team.id,
                        "timestamp": f"2025-12-16 {11 + h:02d}:{m:02d}:40",
                        "body": "",
                        "severity_text": "info",
                        "severity_number": 9,
                        "service_name": "batched_window_b",
                        "resource_attributes": {},
                        "attributes_map_str": {},
                    }
                )
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

        alert_a = self._make_alert(name="A", filters={"serviceNames": ["batched_window_a"]})
        alert_b = self._make_alert(name="B", filters={"serviceNames": ["batched_window_b"]})

        nca = datetime(2025, 12, 16, 13, 0, tzinfo=UTC) + dt.timedelta(minutes=offset_minutes)
        date_from = nca - dt.timedelta(minutes=60)

        result = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert_a, alert_b], date_from=date_from, date_to=nca
        ).execute_periods(period_minutes=20, period_count=3)

        # Every period for A: 20 logs (1/min × 20 min). Every period for B: 40 logs (2/min × 20 min).
        a_counts = [b.count for b in result.per_alert[str(alert_a.id)]]
        b_counts = [b.count for b in result.per_alert[str(alert_b.id)]]
        assert a_counts == [20, 20, 20], (
            f"NCA offset {offset_minutes}min: alert A per-period counts diverge from constant 20; got {a_counts}"
        )
        assert b_counts == [40, 40, 40], (
            f"NCA offset {offset_minutes}min: alert B per-period counts diverge from constant 40; got {b_counts}"
        )

    @freeze_time("2025-12-16T11:00:00Z")
    def test_per_alert_results_match_single_query_across_random_inputs(self):
        # Generative property test: the batched query must produce the same
        # per-alert bucket counts as running each alert through `AlertCheckQuery`
        # individually. We seed several services worth of logs at random
        # timestamps (a random subset carrying a log attribute), build one alert
        # per service (alternating service-only and service+attribute filters),
        # run them as a batched cohort, and assert each alert's per_alert slice
        # matches the single-alert result.
        # Sparse buckets (count=0 in batched, absent in single) are reconciled by
        # filtering count>0 before comparison — same convention as the single
        # query test suite.
        import random as _random

        rng = _random.Random(7)
        base = datetime(2025, 12, 16, 9, 0, 0, tzinfo=UTC)
        range_seconds = 2 * 3600
        attr_values = ["alpha", "beta", "gamma"]

        # Build N services, each with a random log distribution.
        n_services = 6
        all_rows: list[dict] = []
        services: list[str] = []
        for trial in range(n_services):
            service_name = f"batched_equiv_test_{trial}"
            services.append(service_name)
            n_logs = rng.randint(0, 150)  # include 0 so we exercise sparse alerts
            for i in range(n_logs):
                off = rng.randint(0, range_seconds - 1)
                attributes = {"job_kind__str": rng.choice(attr_values)} if rng.random() < 0.5 else {}
                all_rows.append(
                    _log_row(
                        self.team.id,
                        f"batched-equiv-{trial}-{i}",
                        (base + dt.timedelta(seconds=off)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                        service_name,
                        attributes=attributes,
                    )
                )
        if all_rows:
            sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in all_rows))

        # Attribute alerts read the attributes_map_str map, the filter class
        # whose predicate placement caused the production incident.
        alerts = [
            self._make_alert(name=svc, filters={"serviceNames": [svc]})
            if trial % 2 == 0
            else self._make_alert(
                name=f"{svc}-attr",
                filters=_attribute_filters("job_kind", attr_values[trial % len(attr_values)], services=[svc]),
            )
            for trial, svc in enumerate(services)
        ]
        date_from = base
        date_to = base + dt.timedelta(seconds=range_seconds)

        for bucket_minutes in (1, 5, 15, 30):
            batched = BatchedAlertCheckQuery(
                team=self.team, alerts=alerts, date_from=date_from, date_to=date_to
            ).execute_bucketed(interval_minutes=bucket_minutes, limit=10_000)

            for alert in alerts:
                single = AlertCheckQuery(
                    team=self.team, alert=alert, date_from=date_from, date_to=date_to
                ).execute_bucketed(interval_minutes=bucket_minutes, limit=10_000)
                batched_for_alert = batched.per_alert[str(alert.id)]
                non_zero_batched = [b for b in batched_for_alert if b.count > 0]
                assert non_zero_batched == single, (
                    f"alert={alert.name} bucket_minutes={bucket_minutes}\n"
                    f"batched (non-zero): {non_zero_batched}\n"
                    f"single:             {single}"
                )

    @freeze_time("2025-12-16T11:00:00Z")
    def test_sparse_alert_in_busy_cohort_returns_zero_counts(self):
        # Multi-alert cohort where one alert has matches and one is sparse:
        # confirm the sparse alert's per_alert slice contains only zeros (the
        # busy alert's slice is non-empty). Verifies the cohort scan emits a
        # bucket per data-bearing timestamp and the zero-matching alert reports
        # a 0 for every such bucket.
        rows = [
            {
                "uuid": f"busy-{i}",
                "team_id": self.team.id,
                "timestamp": ts,
                "body": "",
                "severity_text": "info",
                "severity_number": 9,
                "service_name": "batched_busy",
                "resource_attributes": {},
                "attributes_map_str": {},
            }
            for i, ts in enumerate(
                [
                    "2025-12-16 10:00:30",
                    "2025-12-16 10:01:00",
                    "2025-12-16 10:05:30",
                ]
            )
        ]
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

        busy = self._make_alert(name="busy", filters={"serviceNames": ["batched_busy"]})
        sparse = self._make_alert(name="sparse", filters={"serviceNames": ["batched_sparse_no_data"]})
        result = BatchedAlertCheckQuery(
            team=self.team,
            alerts=[busy, sparse],
            date_from=datetime(2025, 12, 16, 10, 0, 0, tzinfo=UTC),
            date_to=datetime(2025, 12, 16, 10, 10, 0, tzinfo=UTC),
        ).execute_bucketed(interval_minutes=5)

        busy_buckets = result.per_alert[str(busy.id)]
        sparse_buckets = result.per_alert[str(sparse.id)]

        # Cohort scan emitted buckets for the data-bearing timestamps; busy's
        # counts sum to the inserted log count, sparse's are all zero.
        assert sum(b.count for b in busy_buckets) == len(rows)
        assert sparse_buckets, "expected the cohort scan to emit buckets covering busy's data"
        assert all(b.count == 0 for b in sparse_buckets)
        assert [b.timestamp for b in busy_buckets] == [b.timestamp for b in sparse_buckets]

    @freeze_time("2025-12-16T10:33:00Z")
    def test_excludes_log_at_exact_date_to(self):
        # Half-open [date_from, date_to). A log timestamped exactly at date_to
        # must be excluded for every alert in the cohort.
        rows = [
            {
                "uuid": f"bnd-{i}",
                "team_id": self.team.id,
                "timestamp": ts,
                "body": "",
                "severity_text": "info",
                "severity_number": 9,
                "service_name": "batched_boundary",
                "resource_attributes": {},
                "attributes_map_str": {},
            }
            for i, ts in enumerate(
                [
                    "2025-12-16 10:09:59.999999",  # included
                    "2025-12-16 10:10:00.000000",  # exactly date_to → excluded
                ]
            )
        ]
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

        alert = self._make_alert(filters={"serviceNames": ["batched_boundary"]})
        result = BatchedAlertCheckQuery(
            team=self.team,
            alerts=[alert],
            date_from=datetime(2025, 12, 16, 10, 0, 0, tzinfo=UTC),
            date_to=datetime(2025, 12, 16, 10, 10, 0, tzinfo=UTC),
        ).execute_bucketed(interval_minutes=5)

        non_zero = {
            (b.timestamp.replace(tzinfo=UTC) if b.timestamp.tzinfo is None else b.timestamp): b.count
            for b in result.per_alert[str(alert.id)]
            if b.count > 0
        }
        # Only the .999999 log is counted; the .000000 log at date_to is excluded.
        assert non_zero == {datetime(2025, 12, 16, 10, 5, 0, tzinfo=UTC): 1}

    @freeze_time("2025-12-17T01:00:00Z")
    def test_buckets_correct_across_midnight_boundary(self):
        # Cadence-grid bucketing anchors at midnight UTC — buckets that span
        # the day rollover must land in the right slot in the batched path too.
        rows = [
            {
                "uuid": f"mid-{i}",
                "team_id": self.team.id,
                "timestamp": ts,
                "body": "",
                "severity_text": "info",
                "severity_number": 9,
                "service_name": "batched_midnight",
                "resource_attributes": {},
                "attributes_map_str": {},
            }
            for i, ts in enumerate(
                [
                    "2025-12-16 23:55:00.000000",  # bucket [23:55, 24:00)
                    "2025-12-16 23:59:59.999999",  # bucket [23:55, 24:00)
                    "2025-12-17 00:00:00.000000",  # bucket [00:00, 00:05)
                    "2025-12-17 00:04:59.999999",  # bucket [00:00, 00:05)
                    "2025-12-17 00:05:00.000000",  # bucket [00:05, 00:10)
                ]
            )
        ]
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

        alert = self._make_alert(filters={"serviceNames": ["batched_midnight"]})
        result = BatchedAlertCheckQuery(
            team=self.team,
            alerts=[alert],
            date_from=datetime(2025, 12, 16, 23, 50, 0, tzinfo=UTC),
            date_to=datetime(2025, 12, 17, 0, 10, 0, tzinfo=UTC),
        ).execute_bucketed(interval_minutes=5)

        actual = {
            (b.timestamp.replace(tzinfo=UTC) if b.timestamp.tzinfo is None else b.timestamp): b.count
            for b in result.per_alert[str(alert.id)]
            if b.count > 0
        }
        expected = {
            datetime(2025, 12, 16, 23, 55, 0, tzinfo=UTC): 2,
            datetime(2025, 12, 17, 0, 0, 0, tzinfo=UTC): 2,
            datetime(2025, 12, 17, 0, 5, 0, tzinfo=UTC): 1,
        }
        assert actual == expected

    @freeze_time("2025-12-16T10:33:00Z")
    def test_subsecond_precision_at_boundaries(self):
        # DateTime64(6) precision: a log at :04:59.999999 belongs in [10:00, 10:05);
        # one at :05:00.000000 belongs in [10:05, 10:10). Ensure batched bucket
        # alignment respects that.
        rows = [
            {
                "uuid": f"sub-{i}",
                "team_id": self.team.id,
                "timestamp": ts,
                "body": "",
                "severity_text": "info",
                "severity_number": 9,
                "service_name": "batched_subsecond",
                "resource_attributes": {},
                "attributes_map_str": {},
            }
            for i, ts in enumerate(
                [
                    "2025-12-16 10:04:59.999999",  # bucket [10:00, 10:05)
                    "2025-12-16 10:05:00.000000",  # bucket [10:05, 10:10)
                    "2025-12-16 10:05:00.000001",  # bucket [10:05, 10:10)
                ]
            )
        ]
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

        alert = self._make_alert(filters={"serviceNames": ["batched_subsecond"]})
        result = BatchedAlertCheckQuery(
            team=self.team,
            alerts=[alert],
            date_from=datetime(2025, 12, 16, 10, 0, 0, tzinfo=UTC),
            date_to=datetime(2025, 12, 16, 10, 10, 0, tzinfo=UTC),
        ).execute_bucketed(interval_minutes=5)

        actual = {
            (b.timestamp.replace(tzinfo=UTC) if b.timestamp.tzinfo is None else b.timestamp): b.count
            for b in result.per_alert[str(alert.id)]
            if b.count > 0
        }
        assert actual == {
            datetime(2025, 12, 16, 10, 0, 0, tzinfo=UTC): 1,
            datetime(2025, 12, 16, 10, 5, 0, tzinfo=UTC): 2,
        }

    @freeze_time("2025-12-16T10:33:00Z")
    def test_bucket_placement_matches_single_query(self):
        # Targeted equivalence test: seed five logs at known timestamps that
        # split across two 5-minute buckets, run batched with two alerts (one
        # service-only, one service+severity), assert per-alert results match
        # the single-alert path bucket-for-bucket.
        rows = [
            {
                "uuid": f"placement-{i}",
                "team_id": self.team.id,
                "timestamp": ts,
                "body": "",
                "severity_text": severity,
                "severity_number": 9,
                "service_name": "batched_placement",
                "resource_attributes": {},
                "attributes_map_str": {},
            }
            for i, (ts, severity) in enumerate(
                [
                    ("2025-12-16 10:00:30", "info"),
                    ("2025-12-16 10:01:00", "warn"),
                    ("2025-12-16 10:04:59", "info"),
                    ("2025-12-16 10:05:00", "info"),
                    ("2025-12-16 10:09:59", "warn"),
                ]
            )
        ]
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

        all_alert = self._make_alert(name="all", filters={"serviceNames": ["batched_placement"]})
        info_alert = self._make_alert(
            name="info_only",
            filters={"serviceNames": ["batched_placement"], "severityLevels": ["info"]},
        )
        date_from = datetime(2025, 12, 16, 10, 0, 0, tzinfo=UTC)
        date_to = datetime(2025, 12, 16, 10, 10, 0, tzinfo=UTC)

        batched = BatchedAlertCheckQuery(
            team=self.team, alerts=[all_alert, info_alert], date_from=date_from, date_to=date_to
        ).execute_bucketed(interval_minutes=5)

        for alert in (all_alert, info_alert):
            single = AlertCheckQuery(
                team=self.team, alert=alert, date_from=date_from, date_to=date_to
            ).execute_bucketed(interval_minutes=5)
            non_zero_batched = [b for b in batched.per_alert[str(alert.id)] if b.count > 0]
            assert non_zero_batched == single, (
                f"alert={alert.name}\nbatched (non-zero): {non_zero_batched}\nsingle:             {single}"
            )

    @parameterized.expand([("bucketed",), ("periods",), ("rolling",)])
    @freeze_time("2025-12-16T10:33:00Z")
    def test_heterogeneous_cohort_matches_single_alert_results(self, path: str):
        # Cohort mixing a match-everything alert (its predicate is ~always true),
        # a service alert, an attribute alert, and a zero-match alert. Guards the
        # hoisted OR of predicates against a future "simplification" when one
        # disjunct is trivially true, across all three execute paths.
        alerts = [
            self._make_alert(name="everything", filters={}),
            self._make_alert(name="service", filters={"serviceNames": ["argo-rollouts"]}),
            self._make_alert(name="attribute", filters=_attribute_filters("log.iostream", "stderr")),
            self._make_alert(name="nothing", filters={"serviceNames": ["no-such-service"]}),
        ]
        date_from, date_to = self._date_range()

        def run(query):
            if path == "bucketed":
                return query.execute_bucketed(interval_minutes=5)
            if path == "periods":
                return query.execute_periods(period_minutes=5, period_count=3)
            return query.execute_rolling_checks(nca=date_to, window_minutes=5, cadence_minutes=5, period_count=3)

        batched = run(BatchedAlertCheckQuery(team=self.team, alerts=alerts, date_from=date_from, date_to=date_to))
        for alert in alerts:
            single = run(AlertCheckQuery(team=self.team, alert=alert, date_from=date_from, date_to=date_to))
            got = batched.per_alert[str(alert.id)]
            if path == "bucketed":
                got = [b for b in got if b.count > 0]
            assert got == single, f"alert={alert.name} path={path}"

    @freeze_time("2025-12-16T13:30:00Z")
    def test_max_cohort_size_query_builds_and_matches(self):
        # A full-size cohort duplicates every predicate into the hoisted OR
        # chain on top of its countIf copy: guards the doubled predicate text
        # against query-size/printer limits at the production cohort cap, with
        # spot-checked equivalence.
        nca = datetime(2025, 12, 16, 12, 30, tzinfo=UTC)
        date_from = nca - dt.timedelta(minutes=15)
        sampled = (0, MAX_ALERT_COHORT_SIZE // 2, MAX_ALERT_COHORT_SIZE - 1)
        for i in sampled:
            _seed_log_rows(self.team.id, f"batched_cap_{i}", date_from, [1] * 15, f"cap-{i}")

        alerts = [
            self._make_alert(name=f"cap-{i}", filters={"serviceNames": [f"batched_cap_{i}"]})
            for i in range(MAX_ALERT_COHORT_SIZE)
        ]
        batched = BatchedAlertCheckQuery(
            team=self.team, alerts=alerts, date_from=date_from, date_to=nca
        ).execute_rolling_checks(nca=nca, window_minutes=5, cadence_minutes=5, period_count=3)

        assert set(batched.per_alert.keys()) == {str(a.id) for a in alerts}
        for i in sampled:
            single = AlertCheckQuery(
                team=self.team, alert=alerts[i], date_from=date_from, date_to=nca
            ).execute_rolling_checks(nca=nca, window_minutes=5, cadence_minutes=5, period_count=3)
            assert batched.per_alert[str(alerts[i].id)] == single, f"alert index {i}"
            assert sum(b.count for b in single) > 0


# Predicate hoisting: the batched query's outer WHERE carries the OR of
# per-alert predicates so ClickHouse can prune with the primary key and skip
# indexes. The redundant-looking OR is the point: removing it reverts to
# scanning the whole time window, the shape that made attribute-filter alerts
# exceed the 5 GiB read cap and auto-disable in production.
class TestBatchedQueryPredicateHoisting(ClickhouseTestMixin, APIBaseTest):
    ATTR_KEY = "job_kind"
    ATTR_VALUE = "usage-rollup"
    TARGET_SERVICE = "hoist_usage_reporter"
    NOISY_SERVICES = ("hoist_noisy_api", "hoist_noisy_worker", "hoist_noisy_web")
    NCA = datetime(2026, 2, 3, 10, 5, 0, tzinfo=UTC)

    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Bulk of the team's volume comes from services the target alert does
        # not match, mirroring the production incident's data shape.
        base = datetime(2026, 2, 3, 9, 50, 0, tzinfo=UTC)
        for svc in cls.NOISY_SERVICES:
            _seed_log_rows(cls.team.id, svc, base, [3] * 15, f"hoist-noise-{svc}")
        attrs = {f"{cls.ATTR_KEY}__str": cls.ATTR_VALUE}
        rows = [
            _log_row(
                cls.team.id,
                "hoist-target-1",
                "2026-02-03 10:01:10",
                cls.TARGET_SERVICE,
                severity="error",
                attributes=attrs,
            ),
            _log_row(
                cls.team.id,
                "hoist-target-2",
                "2026-02-03 10:02:20",
                cls.TARGET_SERVICE,
                severity="error",
                attributes=attrs,
            ),
            # Same service and attribute but wrong severity: must be excluded
            # by the severity leg of the predicate.
            _log_row(
                cls.team.id,
                "hoist-target-3",
                "2026-02-03 10:03:30",
                cls.TARGET_SERVICE,
                severity="info",
                attributes=attrs,
            ),
            # Same service and severity but no attribute: must be excluded by
            # the attribute leg.
            _log_row(cls.team.id, "hoist-target-4", "2026-02-03 10:04:40", cls.TARGET_SERVICE, severity="error"),
            # Rows with bodies for body-filter alerts, the only filter class
            # whose predicate carries an indexHint(...). The resource attribute
            # feeds the log_attributes materialized view so resource-attribute
            # filters resolve to a `resource_fingerprint IN (subquery)` set.
            _log_row(
                cls.team.id,
                "hoist-body-1",
                "2026-02-03 10:01:15",
                cls.TARGET_SERVICE,
                severity="error",
                body="task_crashed",
                resource_attributes={"deployment.environment": "production"},
            ),
            _log_row(
                cls.team.id,
                "hoist-body-2",
                "2026-02-03 10:02:25",
                cls.TARGET_SERVICE,
                severity="error",
                body="nightly export failed: connection reset by peer",
                resource_attributes={"deployment.environment": "production"},
            ),
            # Wrong severity: must be excluded by the severity leg.
            _log_row(
                cls.team.id,
                "hoist-body-3",
                "2026-02-03 10:03:35",
                cls.TARGET_SERVICE,
                severity="info",
                body="nightly export failed: retrying",
                resource_attributes={"deployment.environment": "production"},
            ),
        ]
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

    def _make_alert(self, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "Hoisting test",
            "threshold_count": 0,
            "threshold_operator": "above",
            "window_minutes": 5,
            "evaluation_periods": 3,
            "filters": {},
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    def _incident_filters(self, attr_value: str) -> dict:
        return _attribute_filters(
            self.ATTR_KEY, attr_value, services=[self.TARGET_SERVICE], severities=["error", "fatal"]
        )

    def _print_query(self, query: ast.SelectQuery) -> tuple[str, dict]:
        # Same modifier resolution and {filters} placeholder handling as
        # `execute_hogql_query`, so the printed SQL is the production query text.
        query = replace_filters(query, None, self.team)
        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
            modifiers=create_default_modifiers_for_team(self.team, HogQLQueryModifiers(convertToProjectTimezone=False)),
        )
        sql, _ = prepare_and_print_ast(query, context, "clickhouse")
        return sql, context.values

    @staticmethod
    def _outer_where_sql(sql: str) -> str:
        # The countIf predicates live in the SELECT list, before the WHERE
        # keyword, so everything after it (minus trailing clauses) is the
        # outer WHERE.
        _, sep, after = sql.partition(" WHERE ")
        assert sep, f"no WHERE clause in: {sql}"
        for terminator in (" GROUP BY ", " ORDER BY ", " LIMIT "):
            cut = after.find(terminator)
            if cut != -1:
                after = after[:cut]
        return after

    def _build_two_alert_query(self, builder: str) -> ast.SelectQuery:
        service_alert = self._make_alert(name="svc", filters={"serviceNames": [self.NOISY_SERVICES[0]]})
        attr_alert = self._make_alert(name="attr", filters=self._incident_filters(self.ATTR_VALUE))
        date_from = self.NCA - dt.timedelta(minutes=15)
        query = BatchedAlertCheckQuery(
            team=self.team,
            alerts=[service_alert, attr_alert],
            date_from=date_from,
            date_to=self.NCA,
            projection_eligible=False,
        )
        builders = {
            "bucketed": lambda: query._build_bucketed_query(5, 10_000),
            "count_per_range": lambda: query._build_count_per_range_query(_rolling_check_ranges(self.NCA, 5, 5, 3)),
        }
        return builders[builder]()

    @parameterized.expand(
        [
            ("matches_rows", "usage-rollup", 2),
            ("matches_nothing", "no-such-kind", 0),
        ]
    )
    @freeze_time("2026-02-03T10:05:00Z")
    def test_single_alert_attribute_filter_cohort_matches_per_alert_path(
        self, _name: str, attr_value: str, expected_total: int
    ):
        # The production incident shape: a size-1 cohort whose alert filters on
        # a log attribute (projection-ineligible), checked as 3 rolling 5-minute
        # windows while other services carry the bulk of the team's volume.
        alert = self._make_alert(filters=self._incident_filters(attr_value))
        date_from = self.NCA - dt.timedelta(minutes=15)

        batched = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert], date_from=date_from, date_to=self.NCA, projection_eligible=False
        ).execute_rolling_checks(nca=self.NCA, window_minutes=5, cadence_minutes=5, period_count=3)
        single = AlertCheckQuery(
            team=self.team, alert=alert, date_from=date_from, date_to=self.NCA
        ).execute_rolling_checks(nca=self.NCA, window_minutes=5, cadence_minutes=5, period_count=3)

        assert batched.per_alert[str(alert.id)] == single
        assert sum(b.count for b in single) == expected_total

    @parameterized.expand([("bucketed",), ("count_per_range",)])
    def test_alert_predicates_hoisted_into_outer_where(self, builder: str):
        # If a refactor drops the "redundant" OR from the outer WHERE, every
        # equivalence test still passes (the predicates survive inside countIf)
        # and the scan just quietly stops pruning. Pin the placement.
        sql, _ = self._print_query(self._build_two_alert_query(builder))
        where = self._outer_where_sql(sql)
        assert "service_name" in where
        assert "attributes_map_str" in where

    def test_single_alert_outer_where_has_bare_predicate(self):
        # A size-1 cohort must produce the same WHERE shape as AlertCheckQuery:
        # the predicate itself, not a one-armed or(...) wrapper.
        alert = self._make_alert(filters={"serviceNames": [self.TARGET_SERVICE]})
        date_from = self.NCA - dt.timedelta(minutes=15)
        query = BatchedAlertCheckQuery(team=self.team, alerts=[alert], date_from=date_from, date_to=self.NCA)
        sql, _ = self._print_query(query._build_count_per_range_query(_rolling_check_ranges(self.NCA, 5, 5, 3)))
        where = self._outer_where_sql(sql)
        assert "service_name" in where
        assert not re.search(r"(?<![a-zA-Z0-9_])or\(", where), where

    def _explain_index_usage(self) -> tuple[set[str], set[str]]:
        alert = self._make_alert(filters=self._incident_filters(self.ATTR_VALUE))
        date_from = self.NCA - dt.timedelta(minutes=15)
        query = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert], date_from=date_from, date_to=self.NCA, projection_eligible=False
        )
        sql, values = self._print_query(query._build_count_per_range_query(_rolling_check_ranges(self.NCA, 5, 5, 3)))
        # Apply the runtime CH settings; index selection can diverge from real
        # queries without them (same recipe as posthog/hogql/test/test_property_skip_indexes.py).
        settings = {
            k: "1" if v is True else "0" if v is False else str(v)
            for k, v in HogQLGlobalSettings().model_dump().items()
            if v is not None
        }
        [[raw]] = sync_execute(f"EXPLAIN indexes = 1, json = 1 {sql}", values, settings=settings)
        plan = json.loads(raw)

        skip_indexes: set[str] = set()
        primary_key_columns: set[str] = set()

        def walk(obj) -> None:
            if isinstance(obj, dict):
                indexes = obj.get("Indexes")
                if isinstance(indexes, list):
                    for idx in indexes:
                        if not isinstance(idx, dict):
                            continue
                        if idx.get("Type") == "Skip" and isinstance(idx.get("Name"), str):
                            skip_indexes.add(idx["Name"])
                        if idx.get("Type") == "PrimaryKey":
                            primary_key_columns.update(k for k in idx.get("Keys", []) if isinstance(k, str))
                for value in obj.values():
                    walk(value)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(plan)
        return skip_indexes, primary_key_columns

    def test_hoisted_predicates_visible_to_planner(self):
        # Plan-level check, because the SQL can contain the predicate in a form
        # the planner cannot use: the primary key must prune on service_name
        # and the mapValues(attributes_map_str) bloom filter must be consulted.
        # `logs` is a Distributed wrapper; the skip indexes live on whichever
        # MergeTree backs it, so look them up by expression instead of by name
        # or table (index names differ between logs schema generations).
        attr_index_rows = sync_execute(
            "SELECT DISTINCT name FROM system.data_skipping_indices"
            " WHERE database = currentDatabase() AND expr LIKE '%attributes_map_str%'"
        )
        attr_indexes = {row[0] for row in attr_index_rows}
        assert attr_indexes, "expected the logs tables to define skip indexes over attributes_map_str"

        hoisted_skips, hoisted_pk = self._explain_index_usage()

        assert "service_name" in hoisted_pk
        assert hoisted_skips & attr_indexes, f"skip indexes in plan: {hoisted_skips}"

    @parameterized.expand(
        [
            (
                "midnight_boundary",
                ["2026-02-02 23:59:59.999999", "2026-02-03 00:00:00.000000"],
                datetime(2026, 2, 2, 23, 50, 0, tzinfo=UTC),
                datetime(2026, 2, 3, 0, 10, 0, tzinfo=UTC),
                2,
            ),
            (
                "subsecond_bucket_edge",
                ["2026-02-02 10:04:59.999999", "2026-02-02 10:05:00.000000"],
                datetime(2026, 2, 2, 10, 0, 0, tzinfo=UTC),
                datetime(2026, 2, 2, 10, 10, 0, tzinfo=UTC),
                2,
            ),
            (
                "exact_date_to_excluded",
                ["2026-02-02 10:09:59.999999", "2026-02-02 10:10:00.000000"],
                datetime(2026, 2, 2, 10, 0, 0, tzinfo=UTC),
                datetime(2026, 2, 2, 10, 10, 0, tzinfo=UTC),
                1,
            ),
        ]
    )
    @freeze_time("2026-02-03T10:05:00Z")
    def test_boundary_rows_with_attribute_filter(
        self, name: str, timestamps: list[str], date_from: datetime, date_to: datetime, expected_total: int
    ):
        # The existing boundary tests use service filters only; with hoisting,
        # an attribute predicate and the time bounds meet in the outer WHERE
        # for the first time, so pin batched == single at the same edges.
        service = f"hoist_bnd_{name}"
        rows = [
            _log_row(
                self.team.id,
                f"bnd-{name}-{i}",
                ts,
                service,
                attributes={f"{self.ATTR_KEY}__str": self.ATTR_VALUE},
            )
            for i, ts in enumerate(timestamps)
        ]
        # A row without the attribute keeps the attribute leg non-trivial.
        rows.append(_log_row(self.team.id, f"bnd-{name}-decoy", timestamps[0], service))
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

        alert = self._make_alert(filters=_attribute_filters(self.ATTR_KEY, self.ATTR_VALUE, services=[service]))
        batched = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert], date_from=date_from, date_to=date_to, projection_eligible=False
        ).execute_bucketed(interval_minutes=5)
        single = AlertCheckQuery(team=self.team, alert=alert, date_from=date_from, date_to=date_to).execute_bucketed(
            interval_minutes=5
        )

        non_zero = [b for b in batched.per_alert[str(alert.id)] if b.count > 0]
        assert non_zero == single
        assert sum(b.count for b in single) == expected_total

    def _body_filters(self, operator: str, value: str) -> dict:
        return {
            "serviceNames": [self.TARGET_SERVICE],
            "severityLevels": ["error", "fatal"],
            "filterGroup": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": "message", "value": value, "operator": operator, "type": "log"}],
                    }
                ],
            },
        }

    @parameterized.expand(
        [
            ("exact", "exact", "task_crashed", 1),
            ("icontains", "icontains", "export failed", 1),
            ("regex", "regex", "connection reset|task_crashed", 2),
        ]
    )
    @freeze_time("2026-02-03T10:05:00Z")
    def test_body_filter_alert_matches_per_alert_path(self, _name: str, operator: str, value: str, expected: int):
        # Body filters are the only predicates carrying an indexHint(...). With
        # the hint hoisted into the outer WHERE alongside its countIf copy,
        # ClickHouse dedupes the shared expression and rejects the query with
        # ILLEGAL_COLUMN ("non constant in source stream but must be constant
        # in result"), so every check for such an alert fails outright.
        alert = self._make_alert(filters=self._body_filters(operator, value))
        date_from = self.NCA - dt.timedelta(minutes=15)

        batched_rolling = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert], date_from=date_from, date_to=self.NCA, projection_eligible=False
        ).execute_rolling_checks(nca=self.NCA, window_minutes=5, cadence_minutes=5, period_count=3)
        single_rolling = AlertCheckQuery(
            team=self.team, alert=alert, date_from=date_from, date_to=self.NCA
        ).execute_rolling_checks(nca=self.NCA, window_minutes=5, cadence_minutes=5, period_count=3)
        assert batched_rolling.per_alert[str(alert.id)] == single_rolling
        assert sum(b.count for b in single_rolling) == expected

        batched_bucketed = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert], date_from=date_from, date_to=self.NCA, projection_eligible=False
        ).execute_bucketed(interval_minutes=5)
        single_bucketed = AlertCheckQuery(
            team=self.team, alert=alert, date_from=date_from, date_to=self.NCA
        ).execute_bucketed(interval_minutes=5)
        non_zero = [b for b in batched_bucketed.per_alert[str(alert.id)] if b.count > 0]
        assert non_zero == single_bucketed

    @freeze_time("2026-02-03T10:05:00Z")
    def test_body_and_resource_attribute_filter_matches_per_alert_path(self):
        # The full failing shape: the body filter contributes the indexHint and
        # the resource-attribute filter contributes a `resource_fingerprint IN
        # (subquery)` prepared set. With both hoisted verbatim into the outer
        # WHERE, ClickHouse plans the shared expression once, constant-folds
        # its WHERE use but not its countIf use, and rejects the query with
        # ILLEGAL_COLUMN. Body-only predicates survive on some ClickHouse
        # versions; this combination does not.
        filters = self._body_filters("icontains", "export failed")
        filters["filterGroup"]["values"][0]["values"].append(
            {
                "key": "deployment.environment",
                "value": "production",
                "operator": "exact",
                "type": "log_resource_attribute",
            }
        )
        alert = self._make_alert(filters=filters)
        date_from = self.NCA - dt.timedelta(minutes=15)

        batched = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert], date_from=date_from, date_to=self.NCA, projection_eligible=False
        ).execute_rolling_checks(nca=self.NCA, window_minutes=5, cadence_minutes=5, period_count=3)
        single = AlertCheckQuery(
            team=self.team, alert=alert, date_from=date_from, date_to=self.NCA
        ).execute_rolling_checks(nca=self.NCA, window_minutes=5, cadence_minutes=5, period_count=3)

        assert batched.per_alert[str(alert.id)] == single
        assert sum(b.count for b in single) == 1

    def test_hoisted_where_strips_index_hints(self):
        # The countIf copy keeps its indexHint; only the hoisted WHERE copy
        # drops it. If a refactor hoists the hint again, the equivalence tests
        # above only catch it on ClickHouse versions where the plan dedup
        # triggers, so pin the SQL shape too.
        alert = self._make_alert(filters=self._body_filters("icontains", "export failed"))
        date_from = self.NCA - dt.timedelta(minutes=15)
        query = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert], date_from=date_from, date_to=self.NCA, projection_eligible=False
        )
        sql, _ = self._print_query(query._build_count_per_range_query(_rolling_check_ranges(self.NCA, 5, 5, 3)))
        select_part, _, _ = sql.partition(" WHERE ")
        assert "indexHint(" in select_part
        assert "indexHint(" not in self._outer_where_sql(sql)


# No fixture rows on purpose: the ILLEGAL_COLUMN plan failure needs the scan
# to select zero parts, so the constant-folded filter column meets an empty
# source stream. Seeded classes can never hit it; production hits it whenever
# a shard has no matching parts for the check window.
class TestBatchedQueryPredicateHoistingEmptyScan(ClickhouseTestMixin, APIBaseTest):
    @freeze_time("2026-02-03T10:05:00Z")
    def test_body_and_resource_filter_with_no_matching_logs(self):
        alert = LogsAlertConfiguration.objects.create(
            team=self.team,
            name="empty scan",
            threshold_count=0,
            threshold_operator="above",
            window_minutes=5,
            evaluation_periods=3,
            filters={
                "serviceNames": ["quiet_service"],
                "severityLevels": ["error", "fatal"],
                "filterGroup": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "message", "value": "export failed", "operator": "icontains", "type": "log"},
                                {
                                    "key": "deployment.environment",
                                    "value": "production",
                                    "operator": "exact",
                                    "type": "log_resource_attribute",
                                },
                            ],
                        }
                    ],
                },
            },
        )
        nca = datetime(2026, 2, 3, 10, 5, 0, tzinfo=UTC)
        date_from = nca - dt.timedelta(minutes=15)

        batched = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert], date_from=date_from, date_to=nca, projection_eligible=False
        ).execute_rolling_checks(nca=nca, window_minutes=5, cadence_minutes=5, period_count=3)

        assert [b.count for b in batched.per_alert[str(alert.id)]] == [0, 0, 0]


class TestFetchLiveLogsCheckpoint(APIBaseTest):
    @patch("products.logs.backend.alert_check_query.execute_hogql_query")
    def test_returns_datetime_from_response(self, mock_execute):
        mock_response = type("R", (), {"results": [[datetime(2025, 1, 1, 12, 34, 56, tzinfo=UTC)]]})()
        mock_execute.return_value = mock_response

        result = fetch_live_logs_checkpoint(self.team)

        assert result == datetime(2025, 1, 1, 12, 34, 56, tzinfo=UTC)

    @patch("products.logs.backend.alert_check_query.execute_hogql_query")
    def test_returns_none_on_empty_table(self, mock_execute):
        # min() over an empty set returns NULL.
        mock_execute.return_value = type("R", (), {"results": [[None]]})()

        assert fetch_live_logs_checkpoint(self.team) is None

    @patch("products.logs.backend.alert_check_query.execute_hogql_query")
    def test_returns_none_when_no_rows(self, mock_execute):
        mock_execute.return_value = type("R", (), {"results": []})()

        assert fetch_live_logs_checkpoint(self.team) is None

    @patch("products.logs.backend.alert_check_query.execute_hogql_query")
    def test_attaches_utc_to_naive_datetime(self, mock_execute):
        # ClickHouse returns tz-naive datetimes for DateTime64 columns in some code paths.
        mock_execute.return_value = type("R", (), {"results": [[datetime(2025, 1, 1, 12, 34, 56)]]})()

        result = fetch_live_logs_checkpoint(self.team)

        assert result == datetime(2025, 1, 1, 12, 34, 56, tzinfo=UTC)
        assert result is not None and result.tzinfo is not None


class TestResolveAlertDateTo(unittest.TestCase):
    NEXT_CHECK_AT = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_none_checkpoint_returns_next_check_at(self):
        assert resolve_alert_date_to(self.NEXT_CHECK_AT, None) == self.NEXT_CHECK_AT

    def test_fresh_checkpoint_in_past_is_used(self):
        checkpoint = self.NEXT_CHECK_AT - dt.timedelta(seconds=30)
        assert resolve_alert_date_to(self.NEXT_CHECK_AT, checkpoint) == checkpoint

    def test_checkpoint_equal_to_next_check_at_is_used(self):
        assert resolve_alert_date_to(self.NEXT_CHECK_AT, self.NEXT_CHECK_AT) == self.NEXT_CHECK_AT

    def test_future_checkpoint_is_clamped_to_next_check_at(self):
        checkpoint = self.NEXT_CHECK_AT + dt.timedelta(seconds=60)
        assert resolve_alert_date_to(self.NEXT_CHECK_AT, checkpoint) == self.NEXT_CHECK_AT

    def test_stale_checkpoint_beyond_threshold_falls_back_to_next_check_at(self):
        # The "quiet partition pins min() backwards" case — must not strand spikes
        # on active partitions in the past.
        checkpoint = self.NEXT_CHECK_AT - CHECKPOINT_MAX_STALENESS - dt.timedelta(seconds=1)
        assert resolve_alert_date_to(self.NEXT_CHECK_AT, checkpoint) == self.NEXT_CHECK_AT

    def test_checkpoint_exactly_at_threshold_is_still_used(self):
        checkpoint = self.NEXT_CHECK_AT - CHECKPOINT_MAX_STALENESS
        assert resolve_alert_date_to(self.NEXT_CHECK_AT, checkpoint) == checkpoint


class TestRollingCheckRanges(unittest.TestCase):
    NCA = datetime(2026, 5, 3, 6, 0, 0, tzinfo=UTC)

    def test_m_equals_1_returns_single_latest_window(self):
        ranges = _rolling_check_ranges(self.NCA, window_minutes=15, cadence_minutes=5, period_count=1)
        assert ranges == [(self.NCA - dt.timedelta(minutes=15), self.NCA)]

    def test_m_equals_3_window_15_cadence_5(self):
        ranges = _rolling_check_ranges(self.NCA, window_minutes=15, cadence_minutes=5, period_count=3)
        assert ranges == [
            (datetime(2026, 5, 3, 5, 35, tzinfo=UTC), datetime(2026, 5, 3, 5, 50, tzinfo=UTC)),
            (datetime(2026, 5, 3, 5, 40, tzinfo=UTC), datetime(2026, 5, 3, 5, 55, tzinfo=UTC)),
            (datetime(2026, 5, 3, 5, 45, tzinfo=UTC), datetime(2026, 5, 3, 6, 0, tzinfo=UTC)),
        ]

    def test_m_equals_3_window_30_cadence_5(self):
        ranges = _rolling_check_ranges(self.NCA, window_minutes=30, cadence_minutes=5, period_count=3)
        assert ranges == [
            (datetime(2026, 5, 3, 5, 20, tzinfo=UTC), datetime(2026, 5, 3, 5, 50, tzinfo=UTC)),
            (datetime(2026, 5, 3, 5, 25, tzinfo=UTC), datetime(2026, 5, 3, 5, 55, tzinfo=UTC)),
            (datetime(2026, 5, 3, 5, 30, tzinfo=UTC), datetime(2026, 5, 3, 6, 0, tzinfo=UTC)),
        ]

    def test_cadence_equals_window_produces_non_overlapping_back_to_back(self):
        ranges = _rolling_check_ranges(self.NCA, window_minutes=15, cadence_minutes=15, period_count=3)
        assert ranges == [
            (datetime(2026, 5, 3, 5, 15, tzinfo=UTC), datetime(2026, 5, 3, 5, 30, tzinfo=UTC)),
            (datetime(2026, 5, 3, 5, 30, tzinfo=UTC), datetime(2026, 5, 3, 5, 45, tzinfo=UTC)),
            (datetime(2026, 5, 3, 5, 45, tzinfo=UTC), datetime(2026, 5, 3, 6, 0, tzinfo=UTC)),
        ]

    def test_cadence_greater_than_window_produces_gaps(self):
        ranges = _rolling_check_ranges(self.NCA, window_minutes=5, cadence_minutes=10, period_count=3)
        assert ranges == [
            (datetime(2026, 5, 3, 5, 35, tzinfo=UTC), datetime(2026, 5, 3, 5, 40, tzinfo=UTC)),
            (datetime(2026, 5, 3, 5, 45, tzinfo=UTC), datetime(2026, 5, 3, 5, 50, tzinfo=UTC)),
            (datetime(2026, 5, 3, 5, 55, tzinfo=UTC), datetime(2026, 5, 3, 6, 0, tzinfo=UTC)),
        ]

    def test_oldest_first_ordering(self):
        ranges = _rolling_check_ranges(self.NCA, window_minutes=15, cadence_minutes=5, period_count=5)
        starts = [start for start, _ in ranges]
        assert starts == sorted(starts)

    @parameterized.expand(
        [
            ("M1", 1),
            ("M2", 2),
            ("M3", 3),
            ("M5", 5),
            ("M10", 10),
        ]
    )
    def test_newest_range_ends_exactly_at_nca(self, _name: str, m: int):
        ranges = _rolling_check_ranges(self.NCA, window_minutes=15, cadence_minutes=5, period_count=m)
        assert ranges[-1][1] == self.NCA

    def test_total_lookback_matches_window_plus_m_minus_1_times_cadence(self):
        ranges = _rolling_check_ranges(self.NCA, window_minutes=15, cadence_minutes=5, period_count=3)
        oldest_start = ranges[0][0]
        expected_lookback = dt.timedelta(minutes=15 + (3 - 1) * 5)
        assert self.NCA - oldest_start == expected_lookback

    @parameterized.expand(
        [
            ("M1_w15_c5", 1, 15, 5),
            ("M2_w15_c5", 2, 15, 5),
            ("M3_w15_c5", 3, 15, 5),
            ("M5_w30_c5", 5, 30, 5),
            ("M10_w60_c5", 10, 60, 5),
            ("M3_w5_c1", 3, 5, 1),
        ]
    )
    def test_each_range_is_exactly_window_minutes_wide(self, _name: str, m: int, window: int, cadence: int):
        ranges = _rolling_check_ranges(self.NCA, window_minutes=window, cadence_minutes=cadence, period_count=m)
        for start, end in ranges:
            assert end - start == dt.timedelta(minutes=window)

    @parameterized.expand(
        [
            ("M2_w15_c5", 2, 15, 5),
            ("M3_w15_c5", 3, 15, 5),
            ("M5_w30_c5", 5, 30, 5),
        ]
    )
    def test_adjacent_ranges_offset_by_cadence(self, _name: str, m: int, window: int, cadence: int):
        ranges = _rolling_check_ranges(self.NCA, window_minutes=window, cadence_minutes=cadence, period_count=m)
        for i in range(len(ranges) - 1):
            assert ranges[i + 1][0] - ranges[i][0] == dt.timedelta(minutes=cadence)
            assert ranges[i + 1][1] - ranges[i][1] == dt.timedelta(minutes=cadence)
