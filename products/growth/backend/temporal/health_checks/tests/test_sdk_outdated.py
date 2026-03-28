import json

from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.models.health_issue import HealthIssue

from products.growth.backend.temporal.health_checks.sdk_outdated import SdkOutdatedCheck
from products.growth.dags.github_sdk_versions import SDK_TYPES


def _make_github_data(latest_version: str, release_dates: dict | None = None) -> dict:
    return {
        "latestVersion": latest_version,
        "releaseDates": release_dates or {},
    }


def _make_team_data(entries: dict[str, list[dict]]) -> bytes:
    return json.dumps(entries).encode()


class TestSdkOutdatedCheck(TestCase):
    def setUp(self):
        self.check = SdkOutdatedCheck()

    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.get_client")
    def test_detects_outdated_sdk_with_enriched_payload(self, mock_get_client: MagicMock):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        github_data = {"web": _make_github_data("1.200.0", {"1.198.0": "2026-03-01T00:00:00Z"})}
        team_data = _make_team_data(
            {
                "web": [
                    {"lib_version": "1.198.0", "max_timestamp": "2026-03-20T12:00:00Z", "count": 5000},
                    {"lib_version": "1.195.0", "max_timestamp": "2026-03-18T08:00:00Z", "count": 1000},
                ]
            }
        )

        mock_redis.mget.side_effect = [
            [json.dumps(github_data["web"]).encode()],  # github keys
            [team_data],  # team keys
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

    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.get_client")
    def test_skips_team_on_latest_version(self, mock_get_client: MagicMock):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        team_data = _make_team_data(
            {"web": [{"lib_version": "1.200.0", "max_timestamp": "2026-03-20T12:00:00Z", "count": 5000}]}
        )

        mock_redis.mget.side_effect = [
            [json.dumps(_make_github_data("1.200.0")).encode()],
            [team_data],
        ]

        results = self.check.detect([1])

        assert results == {}

    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.get_client")
    def test_returns_empty_when_no_github_data(self, mock_get_client: MagicMock):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.mget.return_value = [None] * len(SDK_TYPES)

        results = self.check.detect([1])

        assert results == {}

    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.get_client")
    def test_skips_team_with_no_cached_data(self, mock_get_client: MagicMock):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        mock_redis.mget.side_effect = [
            [json.dumps(_make_github_data("1.200.0")).encode()],
            [None],  # no team data
        ]

        results = self.check.detect([1])

        assert results == {}
