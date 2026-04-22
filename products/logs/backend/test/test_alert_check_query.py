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
    NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_none_checkpoint_returns_now(self):
        assert resolve_alert_date_to(self.NOW, None) == self.NOW

    def test_fresh_checkpoint_in_past_is_used(self):
        checkpoint = self.NOW - dt.timedelta(seconds=30)
        assert resolve_alert_date_to(self.NOW, checkpoint) == checkpoint

    def test_checkpoint_equal_to_now_is_used(self):
        assert resolve_alert_date_to(self.NOW, self.NOW) == self.NOW

    def test_future_checkpoint_is_clamped_to_now(self):
        checkpoint = self.NOW + dt.timedelta(seconds=60)
        assert resolve_alert_date_to(self.NOW, checkpoint) == self.NOW

    def test_stale_checkpoint_beyond_threshold_falls_back_to_now(self):
        # The "quiet partition pins min() backwards" case — must not strand spikes
        # on active partitions in the past.
        checkpoint = self.NOW - CHECKPOINT_MAX_STALENESS - dt.timedelta(seconds=1)
        assert resolve_alert_date_to(self.NOW, checkpoint) == self.NOW

    def test_checkpoint_exactly_at_threshold_is_still_used(self):
        checkpoint = self.NOW - CHECKPOINT_MAX_STALENESS
        assert resolve_alert_date_to(self.NOW, checkpoint) == checkpoint
