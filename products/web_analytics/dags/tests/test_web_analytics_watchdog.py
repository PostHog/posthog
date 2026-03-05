import datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import Mock, patch

import dagster

from products.web_analytics.dags.web_analytics_watchdog import (
    build_remediation_configs,
    check_partition_accuracy,
    web_analytics_watchdog,
    web_analytics_watchdog_schedule,
)


class TestCheckPartitionAccuracy:
    def setup_method(self):
        self.mock_context = Mock()
        self.mock_context.log = Mock()

    @pytest.mark.parametrize(
        "query_result,expected_status,expected_within_tolerance",
        [
            ([], "NO_DATA", True),
            ([(2, "2024-01-15", 1000, 1000, 0.0, "YES", "GOOD")], "CHECKED", True),
            ([(2, "2024-01-15", 1000, 1020, 2.0, "NO", "FAIR")], "CHECKED", True),
            ([(2, "2024-01-15", 1000, 1100, 10.0, "NO", "POOR")], "CHECKED", False),
            ([(2, "2024-01-15", 1000, 1050, 5.0, "NO", "FAIR")], "CHECKED", True),
        ],
    )
    @patch("products.web_analytics.dags.web_analytics_watchdog.sync_execute")
    @patch("products.web_analytics.dags.web_analytics_watchdog.tags_context")
    @patch("products.web_analytics.dags.web_analytics_watchdog.dagster_tags")
    def test_check_partition_accuracy(
        self,
        _mock_dagster_tags,
        _mock_tags_context,
        mock_sync_execute,
        query_result,
        expected_status,
        expected_within_tolerance,
    ):
        mock_sync_execute.return_value = query_result

        result = check_partition_accuracy(
            context=self.mock_context,
            team_id=2,
            partition_date="2024-01-15",
            tolerance_pct=5.0,
        )

        assert result["status"] == expected_status
        assert result["within_tolerance"] == expected_within_tolerance
        assert result["partition_date"] == "2024-01-15"

    @pytest.mark.parametrize(
        "pct_difference,expected_quality",
        [
            (0.0, "GOOD"),
            (0.5, "GOOD"),
            (1.0, "GOOD"),
            (2.5, "FAIR"),
            (5.0, "FAIR"),
            (5.1, "POOR"),
            (10.0, "POOR"),
        ],
    )
    @patch("products.web_analytics.dags.web_analytics_watchdog.sync_execute")
    @patch("products.web_analytics.dags.web_analytics_watchdog.tags_context")
    @patch("products.web_analytics.dags.web_analytics_watchdog.dagster_tags")
    def test_quality_status_thresholds(
        self,
        _mock_dagster_tags,
        _mock_tags_context,
        mock_sync_execute,
        pct_difference,
        expected_quality,
    ):
        mock_sync_execute.return_value = [(2, "2024-01-15", 1000, 1000, pct_difference, "YES", "GOOD")]

        result = check_partition_accuracy(
            context=self.mock_context,
            team_id=2,
            partition_date="2024-01-15",
            tolerance_pct=5.0,
        )

        assert result["quality_status"] == expected_quality


class TestBuildRemediationConfigs:
    @pytest.mark.parametrize(
        "failing_partitions,expected_count",
        [
            ([], 0),
            (
                [{"partition_date": "2024-01-15", "pct_difference": 6.5, "tolerance_pct": 5.0}],
                1,
            ),
            (
                [
                    {"partition_date": "2024-01-15", "pct_difference": 6.5, "tolerance_pct": 5.0},
                    {"partition_date": "2024-01-16", "pct_difference": 8.0, "tolerance_pct": 5.0},
                ],
                2,
            ),
        ],
    )
    def test_config_count(self, failing_partitions, expected_count):
        configs = build_remediation_configs(failing_partitions)
        assert len(configs) == expected_count

    def test_config_structure(self):
        failing = [{"partition_date": "2024-01-15", "pct_difference": 6.5, "tolerance_pct": 5.0}]
        configs = build_remediation_configs(failing)

        config = configs[0]
        assert config["partition_key"] == "2024-01-15"
        assert config["job_name"] == "web_pre_aggregate_job"
        assert "ops" in config["run_config"]
        assert "web_pre_aggregated_bounces" in config["run_config"]["ops"]
        assert "web_pre_aggregated_stats" in config["run_config"]["ops"]
        assert config["tags"]["triggered_by"] == "watchdog_remediation"
        assert "6.50%" in config["tags"]["reason"]


class TestWebAnalyticsWatchdogAsset:
    @freeze_time("2024-01-20 12:00:00")
    @patch("products.web_analytics.dags.web_analytics_watchdog.check_partition_accuracy")
    def test_all_partitions_passing(self, mock_check):
        mock_check.return_value = {
            "partition_date": "2024-01-15",
            "status": "CHECKED",
            "regular_count": 1000,
            "pre_aggregated_count": 1000,
            "pct_difference": 0.5,
            "within_tolerance": True,
            "quality_status": "GOOD",
        }

        context = dagster.build_asset_context(
            asset_config={"team_id": 2, "lookback_days": 3, "tolerance_pct": 5.0, "dry_run": True}
        )
        result: Any = web_analytics_watchdog(context)

        assert result.metadata["overall_status"].value == "EXCELLENT"
        assert result.metadata["failing_partition_count"].value == 0
        assert result.metadata["total_checked"].value == 3
        assert result.metadata["total_passing"].value == 3
        assert result.metadata["accuracy_rate"].value == 100.0
        assert result.metadata["dry_run"].value is True

    @freeze_time("2024-01-20 12:00:00")
    @patch("products.web_analytics.dags.web_analytics_watchdog.check_partition_accuracy")
    def test_some_partitions_failing(self, mock_check):
        def side_effect(context, team_id, partition_date, tolerance_pct):
            if partition_date == "2024-01-18":
                return {
                    "partition_date": partition_date,
                    "status": "CHECKED",
                    "regular_count": 1000,
                    "pre_aggregated_count": 1100,
                    "pct_difference": 10.0,
                    "within_tolerance": False,
                    "quality_status": "POOR",
                }
            return {
                "partition_date": partition_date,
                "status": "CHECKED",
                "regular_count": 1000,
                "pre_aggregated_count": 1005,
                "pct_difference": 0.5,
                "within_tolerance": True,
                "quality_status": "GOOD",
            }

        mock_check.side_effect = side_effect

        context = dagster.build_asset_context(
            asset_config={"team_id": 2, "lookback_days": 3, "tolerance_pct": 5.0, "dry_run": True}
        )
        result: Any = web_analytics_watchdog(context)

        assert result.metadata["failing_partition_count"].value == 1
        assert result.metadata["total_checked"].value == 3
        assert result.metadata["total_passing"].value == 2

        failing = result.metadata["failing_partitions"].value
        assert len(failing) == 1
        assert failing[0]["partition_date"] == "2024-01-18"

        remediation = result.metadata["remediation_configs"].value
        assert len(remediation) == 1
        assert remediation[0]["partition_key"] == "2024-01-18"

    @freeze_time("2024-01-20 12:00:00")
    @patch("products.web_analytics.dags.web_analytics_watchdog.check_partition_accuracy")
    def test_partition_check_error_handling(self, mock_check):
        mock_check.side_effect = Exception("ClickHouse connection failed")

        context = dagster.build_asset_context(
            asset_config={"team_id": 2, "lookback_days": 2, "tolerance_pct": 5.0, "dry_run": True}
        )

        with pytest.raises(dagster.Failure, match="2 of 2 partition checks failed with errors") as exc_info:
            web_analytics_watchdog(context)

        failure: Any = exc_info.value
        assert failure.metadata["total_checked"].value == 0
        assert failure.metadata["error_count"].value == 2
        assert len(failure.metadata["errors"].value) == 2
        assert failure.metadata["partial_results"].value == []

    @freeze_time("2024-01-20 12:00:00")
    @patch("products.web_analytics.dags.web_analytics_watchdog.check_partition_accuracy")
    def test_partial_errors_still_fail_run(self, mock_check):
        """When some partitions succeed but others error, the run should still fail."""
        call_count = [0]

        def side_effect(context, team_id, partition_date, tolerance_pct):
            call_count[0] += 1
            if call_count[0] == 1:
                return {
                    "partition_date": partition_date,
                    "status": "CHECKED",
                    "regular_count": 1000,
                    "pre_aggregated_count": 1000,
                    "pct_difference": 0.0,
                    "within_tolerance": True,
                    "quality_status": "GOOD",
                }
            raise Exception("ClickHouse connection failed")

        mock_check.side_effect = side_effect

        context = dagster.build_asset_context(
            asset_config={"team_id": 2, "lookback_days": 3, "tolerance_pct": 5.0, "dry_run": True}
        )

        with pytest.raises(dagster.Failure, match="2 of 3 partition checks failed with errors") as exc_info:
            web_analytics_watchdog(context)

        failure: Any = exc_info.value
        assert failure.metadata["total_checked"].value == 1
        assert failure.metadata["error_count"].value == 2
        assert len(failure.metadata["partial_results"].value) == 1

    @freeze_time("2024-01-20 12:00:00")
    @patch("products.web_analytics.dags.web_analytics_watchdog.check_partition_accuracy")
    def test_lookback_days_determines_date_range(self, mock_check):
        mock_check.return_value = {
            "partition_date": "mock",
            "status": "CHECKED",
            "regular_count": 100,
            "pre_aggregated_count": 100,
            "pct_difference": 0.0,
            "within_tolerance": True,
            "quality_status": "GOOD",
        }

        context = dagster.build_asset_context(
            asset_config={"team_id": 2, "lookback_days": 5, "tolerance_pct": 5.0, "dry_run": True}
        )
        web_analytics_watchdog(context)

        assert mock_check.call_count == 5
        checked_dates = [call.args[2] for call in mock_check.call_args_list]
        assert checked_dates == ["2024-01-15", "2024-01-16", "2024-01-17", "2024-01-18", "2024-01-19"]

    @freeze_time("2024-01-20 12:00:00")
    @patch("products.web_analytics.dags.web_analytics_watchdog.check_partition_accuracy")
    def test_dry_run_logs_but_does_not_trigger(self, mock_check):
        mock_check.return_value = {
            "partition_date": "2024-01-19",
            "status": "CHECKED",
            "regular_count": 1000,
            "pre_aggregated_count": 1200,
            "pct_difference": 20.0,
            "within_tolerance": False,
            "quality_status": "POOR",
        }

        context = dagster.build_asset_context(
            asset_config={"team_id": 2, "lookback_days": 1, "tolerance_pct": 5.0, "dry_run": True}
        )
        result: Any = web_analytics_watchdog(context)

        assert result.metadata["dry_run"].value is True
        assert result.metadata["failing_partition_count"].value == 1

    @pytest.mark.parametrize(
        "passing_count,total_count,expected_status",
        [
            (10, 10, "EXCELLENT"),
            (9, 10, "GOOD"),
            (8, 10, "FAIR"),
            (7, 10, "POOR"),
            (0, 10, "POOR"),
        ],
    )
    @freeze_time("2024-01-20 12:00:00")
    @patch("products.web_analytics.dags.web_analytics_watchdog.check_partition_accuracy")
    def test_overall_status_thresholds(self, mock_check, passing_count, total_count, expected_status):
        call_count = [0]

        def side_effect(context, team_id, partition_date, tolerance_pct):
            call_count[0] += 1
            within = call_count[0] <= passing_count
            return {
                "partition_date": partition_date,
                "status": "CHECKED",
                "regular_count": 1000,
                "pre_aggregated_count": 1000 if within else 2000,
                "pct_difference": 0.0 if within else 100.0,
                "within_tolerance": within,
                "quality_status": "GOOD" if within else "POOR",
            }

        mock_check.side_effect = side_effect

        context = dagster.build_asset_context(
            asset_config={"team_id": 2, "lookback_days": total_count, "tolerance_pct": 5.0, "dry_run": True}
        )
        result: Any = web_analytics_watchdog(context)

        assert result.metadata["overall_status"].value == expected_status


class TestWatchdogSchedule:
    @freeze_time("2024-01-20 12:00:00")
    def test_schedule_returns_run_request(self):
        context = dagster.build_schedule_context(scheduled_execution_time=datetime.datetime(2024, 1, 20, 6, 0))
        result = web_analytics_watchdog_schedule(context)

        assert isinstance(result, dagster.RunRequest)
        assert result.run_key == "watchdog_2024-01-20"
        assert result.tags["triggered_by"] == "watchdog_schedule"
