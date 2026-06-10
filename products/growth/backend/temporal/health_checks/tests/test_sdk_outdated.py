from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.health_issue import HealthIssue

from products.growth.backend.constants import TEAM_SDK_CACHE_EXPIRY
from products.growth.backend.temporal.health_checks.sdk_outdated import SdkOutdatedCheck, _cache_team_sdk_data

# A release date far enough in the past that any version behind latest is unambiguously outdated,
# independent of the wall clock when the test runs.
OLD_RELEASE = "2020-01-01T00:00:00Z"


def _make_ch_row(
    team_id: int,
    lib: str,
    lib_version: str,
    max_timestamp: str = "2026-03-20 12:00:00",
    event_count: int = 5000,
) -> tuple:
    return (team_id, lib, lib_version, max_timestamp, event_count)


def _patch_check(github: dict | None, rows: list[tuple]):
    """Patch the three external boundaries the check touches: GitHub version data, ClickHouse, Redis cache."""
    return (
        patch(
            "products.growth.backend.temporal.health_checks.sdk_outdated._load_github_sdk_data",
            return_value=github or {},
        ),
        patch(
            "products.growth.backend.temporal.health_checks.sdk_outdated.execute_clickhouse_health_team_query",
            return_value=rows,
        ),
        patch("products.growth.backend.temporal.health_checks.sdk_outdated._cache_team_sdk_data"),
    )


class TestSdkOutdatedCheck(SimpleTestCase):
    def setUp(self):
        self.check = SdkOutdatedCheck()

    def _run(self, github: dict | None, rows: list[tuple], team_ids: list[int]) -> dict:
        p_github, p_ch, p_cache = _patch_check(github, rows)
        with p_github, p_ch, p_cache as mock_cache:
            self._mock_cache = mock_cache
            return self.check.detect(team_ids)

    def test_detects_outdated_sdk_with_enriched_payload(self):
        github = {
            "web": {"latestVersion": "2.0.0", "releaseDates": {}},
            "posthog-node": {"latestVersion": "3.0.0", "releaseDates": {}},
            "posthog-python": {"latestVersion": "5.0.0", "releaseDates": {"4.0.0": OLD_RELEASE}},
        }
        rows = [
            _make_ch_row(1, "web", "2.0.0"),
            _make_ch_row(1, "posthog-node", "3.0.0"),
            _make_ch_row(1, "posthog-python", "4.0.0", event_count=900),
        ]

        results = self._run(github, rows, [1])

        # Two SDKs are current, one is a major version behind — only the outdated one raises an issue.
        assert 1 in results
        assert len(results[1]) == 1

        issue = results[1][0]
        # 1 of 3 outdated is below the escalation threshold (ceil(3/2)=2), so this stays a warning.
        assert issue.severity == HealthIssue.Severity.WARNING
        assert issue.payload["sdk_name"] == "posthog-python"
        assert issue.payload["latest_version"] == "5.0.0"
        assert issue.payload["current_version"] == "4.0.0"
        assert issue.payload["is_outdated"] is True
        assert "reason" in issue.payload
        assert isinstance(issue.payload["banners"], list)
        assert len(issue.payload["usage"]) == 1
        assert issue.payload["usage"][0]["lib_version"] == "4.0.0"
        assert issue.payload["usage"][0]["is_outdated"] is True
        assert issue.payload["usage"][0]["is_latest"] is False
        assert "status_reason" in issue.payload["usage"][0]
        assert issue.hash_keys == ["sdk_name"]

    def test_alert_reason_explains_significant_outdated_traffic(self):
        # The most-used version already matches latest, but an older version still serves a
        # significant share of traffic. The SDK is flagged, and the alert must explain *that*
        # rather than the contradictory "on 1.142.0, latest is 1.142.0".
        github = {"web": {"latestVersion": "1.142.0", "releaseDates": {"1.130.0": OLD_RELEASE}}}
        rows = [
            _make_ch_row(1, "web", "1.142.0", event_count=700),  # primary: latest, healthy
            _make_ch_row(1, "web", "1.130.0", event_count=300),  # 30% traffic, behind, old
        ]

        results = self._run(github, rows, [1])

        issue = results[1][0]
        assert issue.payload["current_version"] == "1.142.0"
        assert issue.payload["latest_version"] == "1.142.0"
        assert issue.payload["is_outdated"] is True

        # The reason names both the healthy current version and the older version driving the alert.
        reason = issue.payload["reason"]
        assert "1.142.0" in reason
        assert "1.130.0" in reason

        # render_alert forwards the reason verbatim, so the alert is no longer self-contradictory.
        content = SdkOutdatedCheck.render_alert(issue)
        assert content.summary == reason
        assert "1.130.0" in content.summary

    def test_escalates_to_critical_when_majority_outdated(self):
        github = {"posthog-python": {"latestVersion": "5.0.0", "releaseDates": {"4.0.0": OLD_RELEASE}}}
        rows = [_make_ch_row(1, "posthog-python", "4.0.0")]

        results = self._run(github, rows, [1])

        # The team's only SDK is outdated (1 of 1 >= ceil(1/2)), so severity escalates to critical.
        assert results[1][0].severity == HealthIssue.Severity.CRITICAL

    def test_skips_team_on_latest_version(self):
        github = {"web": {"latestVersion": "1.200.0", "releaseDates": {}}}
        rows = [_make_ch_row(1, "web", "1.200.0")]

        assert self._run(github, rows, [1]) == {}

    def test_patch_behind_is_not_flagged(self):
        # Proves the heuristics run: a crude current!=latest rule would flag this, but a patch
        # difference is never outdated.
        github = {"web": {"latestVersion": "2.0.5", "releaseDates": {}}}
        rows = [_make_ch_row(1, "web", "2.0.3")]

        assert self._run(github, rows, [1]) == {}

    def test_returns_empty_when_no_github_data(self):
        p_github, p_ch, p_cache = _patch_check({}, [])
        with p_github, p_ch as mock_ch, p_cache:
            results = self.check.detect([1])
        assert results == {}
        mock_ch.assert_not_called()

    def test_skips_team_with_no_clickhouse_data(self):
        github = {"web": {"latestVersion": "2.0.0", "releaseDates": {}}}
        assert self._run(github, [], [1]) == {}

    def test_multiple_teams_in_batch(self):
        github = {"web": {"latestVersion": "2.0.0", "releaseDates": {}}}
        rows = [
            _make_ch_row(1, "web", "1.0.0"),  # major behind -> outdated
            _make_ch_row(2, "web", "2.0.0"),  # latest -> healthy
            _make_ch_row(3, "web", "1.0.0"),  # major behind -> outdated
        ]

        results = self._run(github, rows, [1, 2, 3])

        assert 1 in results
        assert 2 not in results
        assert 3 in results
        # One result per outdated SDK assessment — guards against regressing to one-per-release.
        assert len(results[1]) == 1
        assert len(results[3]) == 1
        assert results[1][0].payload["sdk_name"] == "web"
        assert results[3][0].payload["sdk_name"] == "web"

    def test_ignores_unknown_sdk_types(self):
        github = {"web": {"latestVersion": "2.0.0", "releaseDates": {}}}
        rows = [_make_ch_row(1, "unknown-sdk", "1.0.0", event_count=100)]

        assert self._run(github, rows, [1]) == {}

    def test_caches_team_data_in_redis(self):
        github = {"web": {"latestVersion": "2.0.0", "releaseDates": {}}}
        rows = [_make_ch_row(1, "web", "1.5.0")]

        self._run(github, rows, [1])

        self._mock_cache.assert_called_once()
        cached_data = self._mock_cache.call_args[0][0]
        assert 1 in cached_data
        assert "web" in cached_data[1]
        assert cached_data[1]["web"][0]["lib_version"] == "1.5.0"

    @patch("products.growth.backend.temporal.health_checks.sdk_outdated.get_client")
    def test_cache_team_sdk_data_uses_team_sdk_cache_expiry(self, mock_get_client: MagicMock):
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe
        mock_get_client.return_value = mock_redis

        _cache_team_sdk_data({1: {"web": [{"lib_version": "1.0.0", "max_timestamp": "x", "count": 1}]}})

        mock_pipe.setex.assert_called_once()
        _key, ttl, _payload = mock_pipe.setex.call_args[0]
        assert ttl == TEAM_SDK_CACHE_EXPIRY


class TestSdkOutdatedRenderAlert(SimpleTestCase):
    def test_render_alert_prefers_reason_when_present(self) -> None:
        reason = (
            "Latest in-use version 1.200.0 matches latest 1.200.0. "
            "Outdated versions still handling >= 20% of traffic: 1.150.0."
        )
        issue = HealthIssue(
            team_id=1,
            kind="sdk_outdated",
            severity=HealthIssue.Severity.WARNING,
            payload={
                "sdk_name": "web",
                "latest_version": "1.200.0",
                "current_version": "1.200.0",
                "reason": reason,
            },
            unique_hash="h",
        )
        content = SdkOutdatedCheck.render_alert(issue)
        assert content.summary == reason

    @parameterized.expand(
        [
            ("safe_version", "1.198.0", "web is on 1.198.0, latest is 1.200.0"),
            ("space_injection", "1.198.0 <https://evil.example|click>", "web is behind 1.200.0"),
            ("newline_injection", "1.198.0\n@channel", "web is behind 1.200.0"),
            ("markdown_injection", "**1.198.0**", "web is behind 1.200.0"),
            ("empty_string", "", "web is behind 1.200.0"),
        ]
    )
    def test_render_alert_rejects_unsafe_current_version(
        self, _name: str, raw_version: str, expected_summary: str
    ) -> None:
        issue = HealthIssue(
            team_id=1,
            kind="sdk_outdated",
            severity=HealthIssue.Severity.WARNING,
            payload={
                "sdk_name": "web",
                "latest_version": "1.200.0",
                "current_version": raw_version,
            },
            unique_hash="h",
        )
        content = SdkOutdatedCheck.render_alert(issue)
        assert content.summary == expected_summary
