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
