import datetime as dt

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.models import HealthCheckBatchSkipped
from posthog.temporal.health_checks.rollups.freshness import RollupWindow

from products.growth.backend.models import SdkVersionsDaily
from products.growth.backend.temporal.health_checks.sdk_outdated import SdkOutdatedCheck

# A release date far enough in the past that any version behind latest is unambiguously outdated,
# independent of the wall clock when the test runs.
OLD_RELEASE = "2020-01-01T00:00:00Z"

WINDOW = RollupWindow(start=dt.date(2026, 3, 14), end=dt.date(2026, 3, 20))


def _make_row(
    team_id: int,
    lib: str,
    lib_version: str | None,
    max_timestamp: dt.datetime = dt.datetime(2026, 3, 20, 12, tzinfo=dt.UTC),
    event_count: int = 5000,
) -> SdkVersionsDaily:
    return SdkVersionsDaily(
        team_id=team_id,
        day=WINDOW.end,
        lib=lib,
        lib_version=lib_version or "",
        event_count=event_count,
        max_timestamp=max_timestamp,
    )


class TestSdkOutdatedCheck(BaseTest):
    def setUp(self):
        super().setUp()
        self.check = SdkOutdatedCheck()

    def _run(self, github: dict | None, rows: list[SdkVersionsDaily], team_ids: list[int]) -> dict:
        SdkVersionsDaily.objects.unscoped().bulk_create(rows)
        with patch(
            "products.growth.backend.temporal.health_checks.sdk_outdated._load_github_sdk_data",
            return_value=github or {},
        ):
            return self.check.detect_from_rollup(team_ids, WINDOW)

    def test_detects_outdated_sdk_with_enriched_payload(self):
        github = {
            "web": {"latestVersion": "2.0.0", "releaseDates": {}},
            "posthog-node": {"latestVersion": "3.0.0", "releaseDates": {}},
            "posthog-python": {"latestVersion": "5.0.0", "releaseDates": {"4.0.0": OLD_RELEASE}},
        }
        rows = [
            _make_row(1, "web", "2.0.0"),
            _make_row(1, "posthog-node", "3.0.0"),
            _make_row(1, "posthog-python", "4.0.0", event_count=900),
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

    def test_detects_legacy_java_without_version_and_recommends_migration(self):
        github = {
            "posthog-java": {
                "latestVersion": "1.2.0",
                "releaseDates": {},
            },
            "posthog-server": {
                "latestVersion": "2.7.5",
                "releaseDates": {},
            },
        }
        rows = [
            _make_row(1, "posthog-java", None),
            _make_row(1, "posthog-server", "2.7.5"),
        ]

        results = self._run(github, rows, [1])

        assert len(results[1]) == 1
        issue = results[1][0]
        assert issue.payload["sdk_name"] == "posthog-java"
        assert issue.payload["latest_version"] == "1.2.0"
        assert issue.payload["migration_source"] == "com.posthog.java:posthog"
        assert issue.payload["migration_target"] == "com.posthog:posthog-server"
        assert "Migrate to com.posthog:posthog-server" in issue.payload["reason"]
        assert issue.payload["usage"][0]["lib_version"] == "Not reported"
        assert issue.payload["usage"][0]["count"] == 5000

        alert = SdkOutdatedCheck.render_alert(issue)
        assert alert.title == "SDK migration recommended"
        assert alert.summary == issue.payload["reason"]

    @parameterized.expand(
        [
            ("posthog-server",),
            ("posthog-rs",),
            ("posthog-rs-mcp",),
            ("posthog-godot",),
            ("posthog-unreal",),
            ("posthog-go-mcp",),
            ("posthog-ruby-mcp",),
            ("js",),
        ]
    )
    def test_sorts_partial_and_full_semver_versions_before_assessment(self, sdk_type: str):
        github = {
            sdk_type: {
                "latestVersion": "2.0.0",
                "releaseDates": {"1.2.0": OLD_RELEASE, "1.10": OLD_RELEASE},
            }
        }
        rows = [
            _make_row(1, sdk_type, "1.2.0", event_count=100),
            _make_row(1, sdk_type, "1.10", event_count=50),
        ]

        results = self._run(github, rows, [1])

        assert results[1][0].payload["current_version"] == "1.10"

    def test_alert_reason_explains_significant_outdated_traffic(self):
        # The most-used version already matches latest, but an older version still serves a
        # significant share of traffic. The SDK is flagged, and the alert must explain *that*
        # rather than the contradictory "on 1.142.0, latest is 1.142.0".
        github = {"web": {"latestVersion": "1.142.0", "releaseDates": {"1.130.0": OLD_RELEASE}}}
        rows = [
            _make_row(1, "web", "1.142.0", event_count=700),  # primary: latest, healthy
            _make_row(1, "web", "1.130.0", event_count=300),  # 30% traffic, behind, old
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
        rows = [_make_row(1, "posthog-python", "4.0.0")]

        results = self._run(github, rows, [1])

        # The team's only SDK is outdated (1 of 1 >= ceil(1/2)), so severity escalates to critical.
        assert results[1][0].severity == HealthIssue.Severity.CRITICAL

    def test_skips_team_on_latest_version(self):
        github = {"web": {"latestVersion": "1.200.0", "releaseDates": {}}}
        rows = [_make_row(1, "web", "1.200.0")]

        assert self._run(github, rows, [1]) == {}

    def test_patch_behind_is_not_flagged(self):
        # Proves the heuristics run: a crude current!=latest rule would flag this, but a patch
        # difference is never outdated.
        github = {"web": {"latestVersion": "2.0.5", "releaseDates": {}}}
        rows = [_make_row(1, "web", "2.0.3")]

        assert self._run(github, rows, [1]) == {}

    def test_skips_batch_when_no_github_data(self):
        with pytest.raises(HealthCheckBatchSkipped):
            self._run({}, [_make_row(1, "web", "1.0.0")], [1])

    def test_keeps_open_issue_for_sdk_without_github_data(self):
        kept_payload = {"sdk_name": "posthog-ruby", "latest_version": "3.0.0", "reason": "behind"}
        HealthIssue.objects.create(
            team_id=self.team.id,
            kind=SdkOutdatedCheck.kind,
            severity=HealthIssue.Severity.WARNING,
            payload=kept_payload,
            unique_hash=HealthIssue.compute_unique_hash(SdkOutdatedCheck.kind, kept_payload, ["sdk_name"]),
        )
        github = {"web": {"latestVersion": "2.0.0", "releaseDates": {}}}

        results = self._run(
            github,
            [_make_row(self.team.id, "web", "1.0.0"), _make_row(self.team.id, "posthog-ruby", "2.0.0")],
            [self.team.id],
        )

        assert sorted(issue.payload["sdk_name"] for issue in results[self.team.id]) == ["posthog-ruby", "web"]
        kept = next(issue for issue in results[self.team.id] if issue.payload["sdk_name"] == "posthog-ruby")
        assert kept.payload == kept_payload

    def test_skips_team_with_no_rollup_data(self):
        github = {"web": {"latestVersion": "2.0.0", "releaseDates": {}}}
        assert self._run(github, [], [1]) == {}

    def test_multiple_teams_in_batch(self):
        github = {"web": {"latestVersion": "2.0.0", "releaseDates": {}}}
        rows = [
            _make_row(1, "web", "1.0.0"),  # major behind -> outdated
            _make_row(2, "web", "2.0.0"),  # latest -> healthy
            _make_row(3, "web", "1.0.0"),  # major behind -> outdated
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
        rows = [_make_row(1, "unknown-sdk", "1.0.0", event_count=100)]

        assert self._run(github, rows, [1]) == {}


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
