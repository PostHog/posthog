import os
import json
import datetime as dt
from datetime import UTC, datetime

import unittest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.logs.backend.alert_check_query import (
    CHECKPOINT_MAX_STALENESS,
    AlertCheckCountResult,
    AlertCheckQuery,
    BatchedAlertCheckQuery,
    BatchedBucketedResult,
    BucketedCount,
    fetch_live_logs_checkpoint,
    is_projection_eligible,
    resolve_alert_date_to,
)
from products.logs.backend.models import LogsAlertConfiguration


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

    @freeze_time("2025-12-16T11:00:00Z")
    def test_per_alert_results_match_single_query_across_random_inputs(self):
        # Generative property test: the batched query must produce the same
        # per-alert bucket counts as running each alert through `AlertCheckQuery`
        # individually. We seed several services worth of logs at random
        # timestamps, build one alert per service, run them as a batched cohort,
        # and assert each alert's per_alert slice matches the single-alert result.
        # Sparse buckets (count=0 in batched, absent in single) are reconciled by
        # filtering count>0 before comparison — same convention as the single
        # query test suite.
        import random as _random

        rng = _random.Random(7)
        base = datetime(2025, 12, 16, 9, 0, 0, tzinfo=UTC)
        range_seconds = 2 * 3600

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
                all_rows.append(
                    {
                        "uuid": f"batched-equiv-{trial}-{i}",
                        "team_id": self.team.id,
                        "timestamp": (base + dt.timedelta(seconds=off)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                        "body": "",
                        "severity_text": "info",
                        "severity_number": 9,
                        "service_name": service_name,
                        "resource_attributes": {},
                        "attributes_map_str": {},
                    }
                )
        if all_rows:
            sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in all_rows))

        alerts = [self._make_alert(name=svc, filters={"serviceNames": [svc]}) for svc in services]
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
