import json

from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.models.health_issue import HealthIssue

from products.growth.backend.constants import SDK_TYPES
from products.growth.backend.temporal.health_checks.sdk_outdated import SdkOutdatedCheck


def _make_github_data(latest_version: str, release_dates: dict | None = None) -> dict:
    return {
        "latestVersion": latest_version,
        "releaseDates": release_dates or {},
    }


def _make_ch_row(
    team_id: int,
    lib: str,
    lib_version: str,
    max_timestamp: str = "2026-03-20 12:00:00",
    event_count: int = 5000,
) -> tuple:
    return (team_id, lib, lib_version, max_timestamp, event_count)


class TestSdkOutdatedCheck(TestCase):
    def setUp(self):
        self.check = SdkOutdatedCheck()

    @patch("products.growth.backend.temporal.health_checks.sdk_outdated._cache_team_sdk_data")
    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.execute_clickhouse_health_team_query")
    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.get_client")
    def test_detects_outdated_sdk_with_enriched_payload(
        self, mock_get_client: MagicMock, mock_ch_query: MagicMock, mock_cache: MagicMock
    ):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.mget.return_value = [
            json.dumps(_make_github_data("1.200.0", {"1.198.0": "2026-03-01T00:00:00Z"})).encode()
        ]

        mock_ch_query.return_value = [
            _make_ch_row(1, "web", "1.198.0", "2026-03-20 12:00:00", 5000),
            _make_ch_row(1, "web", "1.195.0", "2026-03-18 08:00:00", 1000),
        ]

        results = self.check.detect([1])

        assert 1 in results
        assert len(results[1]) == 1

        issue = results[1][0]
        assert issue.severity == HealthIssue.Severity.WARNING
        assert issue.payload["sdk_name"] == "web"
        assert issue.payload["latest_version"] == "1.200.0"
        assert len(issue.payload["usage"]) == 2
        assert issue.payload["usage"][0]["lib_version"] == "1.198.0"
        assert issue.payload["usage"][0]["count"] == 5000
        assert issue.payload["usage"][0]["is_latest"] is False
        assert issue.payload["usage"][0]["release_date"] == "2026-03-01T00:00:00Z"
        assert issue.payload["usage"][1]["lib_version"] == "1.195.0"
        assert issue.payload["usage"][1]["release_date"] is None
        assert issue.hash_keys == ["sdk_name"]

    @patch("products.growth.backend.temporal.health_checks.sdk_outdated._cache_team_sdk_data")
    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.execute_clickhouse_health_team_query")
    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.get_client")
    def test_skips_team_on_latest_version(
        self, mock_get_client: MagicMock, mock_ch_query: MagicMock, mock_cache: MagicMock
    ):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.mget.return_value = [json.dumps(_make_github_data("1.200.0")).encode()]

        mock_ch_query.return_value = [
            _make_ch_row(1, "web", "1.200.0", "2026-03-20 12:00:00", 5000),
        ]

        results = self.check.detect([1])

        assert results == {}

    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.execute_clickhouse_health_team_query")
    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.get_client")
    def test_returns_empty_when_no_github_data(self, mock_get_client: MagicMock, mock_ch_query: MagicMock):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.mget.return_value = [None] * len(SDK_TYPES)

        results = self.check.detect([1])

        assert results == {}
        mock_ch_query.assert_not_called()

    @patch("products.growth.backend.temporal.health_checks.sdk_outdated._cache_team_sdk_data")
    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.execute_clickhouse_health_team_query")
    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.get_client")
    def test_skips_team_with_no_clickhouse_data(
        self, mock_get_client: MagicMock, mock_ch_query: MagicMock, mock_cache: MagicMock
    ):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.mget.return_value = [json.dumps(_make_github_data("1.200.0")).encode()]

        mock_ch_query.return_value = []

        results = self.check.detect([1])

        assert results == {}

    @patch("products.growth.backend.temporal.health_checks.sdk_outdated._cache_team_sdk_data")
    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.execute_clickhouse_health_team_query")
    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.get_client")
    def test_multiple_teams_in_batch(self, mock_get_client: MagicMock, mock_ch_query: MagicMock, mock_cache: MagicMock):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.mget.return_value = [json.dumps(_make_github_data("2.0.0")).encode()]

        mock_ch_query.return_value = [
            _make_ch_row(1, "web", "1.5.0", "2026-03-20 12:00:00", 3000),
            _make_ch_row(2, "web", "2.0.0", "2026-03-20 12:00:00", 1000),
            _make_ch_row(3, "web", "1.0.0", "2026-03-19 08:00:00", 500),
        ]

        results = self.check.detect([1, 2, 3])

        # Team 1 and 3 are outdated, team 2 is on latest
        assert 1 in results
        assert 2 not in results
        assert 3 in results
        assert len(results[1]) == 1
        assert len(results[3]) == 1
        assert results[1][0].payload["sdk_name"] == "web"
        assert results[3][0].payload["sdk_name"] == "web"

    @patch("products.growth.backend.temporal.health_checks.sdk_outdated._cache_team_sdk_data")
    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.execute_clickhouse_health_team_query")
    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.get_client")
    def test_caches_team_data_in_redis(
        self, mock_get_client: MagicMock, mock_ch_query: MagicMock, mock_cache: MagicMock
    ):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.mget.return_value = [json.dumps(_make_github_data("2.0.0")).encode()]

        mock_ch_query.return_value = [
            _make_ch_row(1, "web", "1.5.0", "2026-03-20 12:00:00", 3000),
        ]

        self.check.detect([1])

        mock_cache.assert_called_once()
        cached_data = mock_cache.call_args[0][0]
        assert 1 in cached_data
        assert "web" in cached_data[1]
        assert cached_data[1]["web"][0]["lib_version"] == "1.5.0"

    @patch("products.growth.backend.temporal.health_checks.sdk_outdated._cache_team_sdk_data")
    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.execute_clickhouse_health_team_query")
    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.get_client")
    def test_ignores_unknown_sdk_types(
        self, mock_get_client: MagicMock, mock_ch_query: MagicMock, mock_cache: MagicMock
    ):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.mget.return_value = [json.dumps(_make_github_data("2.0.0")).encode()]

        mock_ch_query.return_value = [
            _make_ch_row(1, "unknown-sdk", "1.0.0", "2026-03-20 12:00:00", 100),
        ]

        results = self.check.detect([1])

        assert results == {}
