from datetime import timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.utils import uuid7

from products.cdp.backend.facade.models import HogFunction
from products.error_tracking.backend.logic.recommendations.alerts import AlertsRecommendation
from products.error_tracking.backend.logic.recommendations.audience_slices import AudienceSlicesRecommendation
from products.error_tracking.backend.logic.recommendations.inflated_counts import InflatedCountsRecommendation
from products.error_tracking.backend.logic.recommendations.long_running_issues import LongRunningIssuesRecommendation
from products.error_tracking.backend.logic.recommendations.rate_limits import RateLimitsRecommendation
from products.error_tracking.backend.logic.recommendations.source_maps import SourceMapsRecommendation
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingRecommendation,
    ErrorTrackingSettings,
    ErrorTrackingStackFrame,
    sync_issues_to_clickhouse,
)

from ee.clickhouse.materialized_columns.columns import materialize

MOCK_ALERTS_META = {
    "alerts": [
        {"key": "error-tracking-issue-created", "enabled": False},
        {"key": "error-tracking-issue-reopened", "enabled": False},
        {"key": "error-tracking-issue-spiking", "enabled": False},
    ]
}
MOCK_ALERTS_META_UPDATED = {
    "alerts": [
        {"key": "error-tracking-issue-created", "enabled": True},
        {"key": "error-tracking-issue-reopened", "enabled": True},
        {"key": "error-tracking-issue-spiking", "enabled": True},
    ]
}


def _days_ago(n: int) -> str:
    return (timezone.now() - timedelta(days=n)).isoformat()


BASE_TYPES = {"alerts", "long_running_issues", "rate_limits", "source_maps"}
IMPACT_TYPES = {
    "audience_slices",
    "fires_on_leave",
    "flow_drop",
    "funnel_step",
    "inflated_counts",
    "known_patterns",
    "lost_visitor",
    "many_accounts",
    "one_account",
    "quick_leave",
    "related_issues",
    "support_tickets",
    "suppressed_events",
}


class TestRecommendationsAPI(ClickhouseTestMixin, APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        materialize("events", "$exception_issue_id", is_nullable=True)

    def _list(self):
        return self.client.get(f"/api/environments/{self.team.id}/error_tracking/recommendations/")

    def _poll(self):
        return self.client.get(f"/api/environments/{self.team.id}/error_tracking/recommendations/?poll=true")

    def _dismiss(self, rec_id):
        return self.client.post(f"/api/environments/{self.team.id}/error_tracking/recommendations/{rec_id}/dismiss/")

    def _refresh(self, rec_id):
        return self.client.post(f"/api/environments/{self.team.id}/error_tracking/recommendations/{rec_id}/refresh/")

    @parameterized.expand(
        [
            ("impact_flag_off", False, BASE_TYPES),
            ("impact_flag_on", True, BASE_TYPES | IMPACT_TYPES),
            # A flag check that fails hides the impact lenses rather than failing the list: fail closed.
            ("impact_flag_check_fails", Exception("flags unavailable"), BASE_TYPES),
        ]
    )
    @patch(
        "products.error_tracking.backend.logic.recommendations.impact_lens.ImpactLens.compute",
        return_value={"window_hours": 24, "issues": []},
    )
    @patch("posthoganalytics.feature_enabled")
    @patch(
        "products.error_tracking.backend.logic.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute",
        return_value={"issues": []},
    )
    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_first_list_creates_all_recommendations(
        self, _name, impact_flag, expected_types, mock_alerts, mock_long_running, mock_flag, mock_lens
    ):
        if isinstance(impact_flag, Exception):
            mock_flag.side_effect = impact_flag
        else:
            mock_flag.return_value = impact_flag
        self.assertEqual(ErrorTrackingRecommendation.objects.filter(team=self.team).count(), 0)

        response = self._list()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(ErrorTrackingRecommendation.objects.filter(team=self.team).count(), len(expected_types))
        types = {r["type"] for r in response.json()["results"]}
        self.assertEqual(types, expected_types)
        self.assertEqual(mock_lens.call_count, len(expected_types & IMPACT_TYPES))

    @patch(
        "products.error_tracking.backend.logic.recommendations.impact_lens.ImpactLens.compute",
        return_value={"window_hours": 24, "issues": []},
    )
    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch(
        "products.error_tracking.backend.logic.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute",
        return_value={"issues": []},
    )
    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_a_team_that_leaves_the_flag_no_longer_sees_or_acts_on_its_lenses(
        self, mock_alerts, mock_long_running, mock_flag, mock_lens
    ):
        lens_id = next(r["id"] for r in self._list().json()["results"] if r["type"] == "flow_drop")

        mock_flag.return_value = False
        response = self._list()

        self.assertEqual({r["type"] for r in response.json()["results"]}, BASE_TYPES)
        for action in ("refresh", "dismiss", "restore"):
            self.assertEqual(
                self.client.post(
                    f"/api/environments/{self.team.id}/error_tracking/recommendations/{lens_id}/{action}/"
                ).status_code,
                status.HTTP_404_NOT_FOUND,
                action,
            )

    @patch(
        "products.error_tracking.backend.logic.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute",
        return_value={"issues": []},
    )
    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
    )
    def test_alerts_recomputes_on_every_list(self, mock_alerts, mock_long_running):
        mock_alerts.return_value = MOCK_ALERTS_META
        self._list()

        mock_alerts.return_value = MOCK_ALERTS_META_UPDATED
        response = self._list()

        self.assertEqual(mock_alerts.call_count, 2)
        alerts = next(r for r in response.json()["results"] if r["type"] == "alerts")
        self.assertEqual(alerts["meta"], MOCK_ALERTS_META_UPDATED)

    @patch(
        "products.error_tracking.backend.logic.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute",
    )
    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_long_running_is_cached_until_interval_elapses(self, mock_alerts, mock_long_running):
        with time_machine.travel("2026-01-01T00:00:00Z", tick=False) as frozen_time:
            mock_long_running.return_value = {"issues": []}
            self._list()
            self.assertEqual(mock_long_running.call_count, 1)

            # Re-listing within the same refresh window doesn't recompute.
            self._list()
            self.assertEqual(mock_long_running.call_count, 1)

            # A full refresh_interval always crosses into the next window — recompute, regardless of phase.
            frozen_time.shift(LongRunningIssuesRecommendation.refresh_interval)
            self._list()
            self.assertEqual(mock_long_running.call_count, 2)

    @patch(
        "products.error_tracking.backend.logic.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute",
        return_value={"issues": []},
    )
    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_dismiss_persists_across_requests(self, mock_alerts, mock_long_running):
        response = self._list()
        alerts_id = next(r["id"] for r in response.json()["results"] if r["type"] == "alerts")

        self._dismiss(alerts_id)

        response = self._list()
        alerts = next(r for r in response.json()["results"] if r["type"] == "alerts")
        self.assertIsNotNone(alerts["dismissed_at"])

    def test_alerts_recommendation_detects_existing_alerts(self):
        HogFunction.objects.create(
            team=self.team,
            type="internal_destination",
            filters={"events": [{"id": "$error_tracking_issue_created", "type": "events"}]},
            hog="return event",
        )
        meta = AlertsRecommendation().compute(self.team)
        by_key = {a["key"]: a["enabled"] for a in meta["alerts"]}
        self.assertTrue(by_key["error-tracking-issue-created"])
        self.assertFalse(by_key["error-tracking-issue-reopened"])
        self.assertFalse(by_key["error-tracking-issue-spiking"])

    def test_alerts_recommendation_ignores_deleted_alerts(self):
        HogFunction.objects.create(
            team=self.team,
            type="internal_destination",
            filters={"events": [{"id": "$error_tracking_issue_created", "type": "events"}]},
            hog="return event",
            deleted=True,
        )
        meta = AlertsRecommendation().compute(self.team)
        by_key = {a["key"]: a["enabled"] for a in meta["alerts"]}
        self.assertFalse(by_key["error-tracking-issue-created"])

    def _create_issue(self, created_at, status=ErrorTrackingIssue.Status.ACTIVE, name="TestError"):
        issue = ErrorTrackingIssue.objects.create(
            id=uuid7(),
            team=self.team,
            status=status,
            name=name,
            description="boom",
        )
        ErrorTrackingIssue.objects.filter(id=issue.id).update(created_at=created_at)
        issue.refresh_from_db()
        fingerprint = f"fp::{issue.id}"
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)
        ErrorTrackingIssueFingerprintV2.objects.filter(team=self.team, fingerprint=fingerprint).update(
            first_seen=created_at
        )
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.pk)
        return issue

    def _create_exception(self, issue_id, timestamp, fingerprint=None):
        _create_event(
            distinct_id="user_1",
            event="$exception",
            team=self.team,
            properties={
                "$exception_issue_id": str(issue_id),
                "$exception_fingerprint": fingerprint or f"fp::{issue_id}",
            },
            timestamp=timestamp,
        )

    def test_audience_slices_flags_issue_concentrated_in_one_browser(self):
        issue = self._create_issue(created_at=timezone.now() - timedelta(days=2), name="FirefoxOnly")
        recent = (timezone.now() - timedelta(hours=1)).isoformat()
        common = {"$lib": "web", "$os": "Windows", "$device_type": "Desktop"}
        for i in range(70):
            properties = {
                **common,
                "$session_id": str(uuid7()),
                "$pageview_id": str(uuid7()),
                "$browser": "Firefox",
                "$browser_version": 141,
                "$exception_issue_id": str(issue.id),
                "$exception_fingerprint": f"fp::{issue.id}",
                # A stack in the app's own code, so the issue is not noise.
                "$exception_types": ["TypeError"],
                "$exception_values": ["Cannot read properties of undefined (reading 'menu')"],
                "$exception_list": [
                    {
                        "type": "TypeError",
                        "value": "Cannot read properties of undefined (reading 'menu')",
                        "stacktrace": {
                            "type": "resolved",
                            "frames": [{"source": "https://app.example.com/app.js", "in_app": True, "resolved": True}],
                        },
                    }
                ],
            }
            _create_event(
                distinct_id=f"user_{i}", event="$exception", team=self.team, properties=properties, timestamp=recent
            )
        for i in range(200):
            browser = "Firefox" if i < 10 else "Chrome"
            properties = {**common, "$session_id": str(uuid7()), "$browser": browser, "$browser_version": 141}
            _create_event(
                distinct_id=f"visitor_{i}", event="$pageview", team=self.team, properties=properties, timestamp=recent
            )
        flush_persons_and_events()

        meta = AudienceSlicesRecommendation().compute(self.team)

        self.assertEqual([i["name"] for i in meta["issues"]], ["FirefoxOnly"])
        slices = {(s["dimension"], s["value"]): s for s in meta["issues"][0]["slices"]}
        self.assertEqual(set(slices), {("browser", "Firefox"), ("browser_version", "Firefox 141")})
        self.assertEqual(slices[("browser", "Firefox")]["issue_share"], 1.0)
        self.assertEqual(slices[("browser", "Firefox")]["baseline_share"], 0.05)

    def test_inflated_counts_flags_issue_driven_by_one_session_on_a_timer(self):
        issue = self._create_issue(created_at=timezone.now() - timedelta(days=2), name="Polling")
        start = timezone.now() - timedelta(hours=6)
        # 40 sessions with one occurrence, 10 sessions repeating every minute, and one session firing every 30 seconds.
        sessions = [(1, 0)] * 40 + [(6, 60)] * 10 + [(100, 30)]
        for occurrences, gap_seconds in sessions:
            session_id = str(uuid7())
            for i in range(occurrences):
                _create_event(
                    distinct_id=session_id,
                    event="$exception",
                    team=self.team,
                    properties={"$session_id": session_id, "$exception_fingerprint": f"fp::{issue.id}"},
                    timestamp=(start + timedelta(seconds=i * gap_seconds)).isoformat(),
                )
        flush_persons_and_events()

        meta = InflatedCountsRecommendation().compute(self.team)

        self.assertEqual([i["name"] for i in meta["issues"]], ["Polling"])
        flagged = meta["issues"][0]
        self.assertEqual(flagged["reasons"], ["top_session", "heavy_sessions", "timer"])
        self.assertEqual((flagged["occurrences"], flagged["sessions"]), (200, 51))
        self.assertEqual(flagged["timer_interval_seconds"], 60)

    def test_long_running_returns_oldest_active_issues_with_recent_occurrences(self):
        old_active = self._create_issue(created_at=timezone.now() - timedelta(days=60), name="Oldest")
        mid_active = self._create_issue(created_at=timezone.now() - timedelta(days=20), name="MidAged")
        recent_active = self._create_issue(created_at=timezone.now() - timedelta(days=3), name="Recent")
        self._create_exception(old_active.id, _days_ago(1))
        self._create_exception(mid_active.id, _days_ago(1))
        # Recent issue still has activity but was first seen <7d ago, so it shouldn't qualify as long-running.
        self._create_exception(recent_active.id, _days_ago(1))
        flush_persons_and_events()

        meta = LongRunningIssuesRecommendation().compute(self.team)

        names = [i["name"] for i in meta["issues"]]
        self.assertEqual(names, ["Oldest", "MidAged"])

    def test_long_running_ignores_issues_without_recent_occurrences(self):
        stale = self._create_issue(created_at=timezone.now() - timedelta(days=60), name="Stale")
        self._create_exception(stale.id, _days_ago(30))
        flush_persons_and_events()

        meta = LongRunningIssuesRecommendation().compute(self.team)

        self.assertEqual(meta["issues"], [])

    def test_long_running_excludes_non_active_issues(self):
        resolved = self._create_issue(
            created_at=timezone.now() - timedelta(days=60),
            status=ErrorTrackingIssue.Status.RESOLVED,
            name="Resolved",
        )
        self._create_exception(resolved.id, _days_ago(1))
        flush_persons_and_events()

        meta = LongRunningIssuesRecommendation().compute(self.team)

        self.assertEqual(meta["issues"], [])

    def test_long_running_limits_to_five(self):
        for i in range(15):
            issue = self._create_issue(
                created_at=timezone.now() - timedelta(days=60 - i),
                name=f"Issue {i:02d}",
            )
            self._create_exception(issue.id, _days_ago(1))
        flush_persons_and_events()

        meta = LongRunningIssuesRecommendation().compute(self.team)

        self.assertEqual(len(meta["issues"]), 5)
        self.assertEqual(meta["issues"][0]["name"], "Issue 00")
        self.assertEqual(meta["issues"][4]["name"], "Issue 04")

    def test_long_running_ignores_other_teams_issues(self):
        other_issue_id = str(uuid4())
        self._create_exception(other_issue_id, _days_ago(1))
        flush_persons_and_events()

        meta = LongRunningIssuesRecommendation().compute(self.team)

        self.assertEqual(meta["issues"], [])

    def test_long_running_enrich_overrides_status_with_live_value(self):
        issue = self._create_issue(created_at=timezone.now() - timedelta(days=60), name="Boom")
        meta = {"issues": [{"id": str(issue.id), "name": "Boom", "status": ErrorTrackingIssue.Status.ACTIVE}]}
        ErrorTrackingIssue.objects.filter(id=issue.id).update(status=ErrorTrackingIssue.Status.SUPPRESSED)

        enriched = LongRunningIssuesRecommendation().enrich(self.team, meta)

        self.assertEqual(enriched["issues"][0]["status"], ErrorTrackingIssue.Status.SUPPRESSED)

    def test_long_running_enrich_with_empty_issues_returns_unchanged(self):
        meta: dict = {"issues": []}

        enriched = LongRunningIssuesRecommendation().enrich(self.team, meta)

        self.assertEqual(enriched, {"issues": []})

    def test_long_running_enrich_keeps_cached_status_when_issue_missing(self):
        meta = {"issues": [{"id": str(uuid4()), "name": "Gone", "status": ErrorTrackingIssue.Status.ACTIVE}]}

        enriched = LongRunningIssuesRecommendation().enrich(self.team, meta)

        self.assertEqual(enriched["issues"][0]["status"], ErrorTrackingIssue.Status.ACTIVE)

    def test_long_running_is_completed_when_no_issues(self):
        self.assertTrue(LongRunningIssuesRecommendation().is_completed({"issues": []}))

    def test_long_running_is_completed_false_when_issues_present(self):
        meta = {"issues": [{"id": "x"}]}
        self.assertFalse(LongRunningIssuesRecommendation().is_completed(meta))

    def test_alerts_is_completed_when_all_enabled(self):
        self.assertTrue(AlertsRecommendation().is_completed(MOCK_ALERTS_META_UPDATED))

    def test_alerts_is_completed_false_when_any_disabled(self):
        partial = {
            "alerts": [
                {"key": "error-tracking-issue-created", "enabled": True},
                {"key": "error-tracking-issue-reopened", "enabled": False},
                {"key": "error-tracking-issue-spiking", "enabled": True},
            ]
        }
        self.assertFalse(AlertsRecommendation().is_completed(partial))

    def test_alerts_is_completed_false_when_empty(self):
        self.assertFalse(AlertsRecommendation().is_completed({"alerts": []}))

    def test_rate_limits_recommendation_with_no_settings(self):
        meta = RateLimitsRecommendation().compute(self.team)
        by_key = {r["key"]: r["enabled"] for r in meta["rate_limits"]}
        self.assertFalse(by_key["project"])
        self.assertFalse(by_key["per_issue"])

    def test_rate_limits_recommendation_detects_set_limits(self):
        ErrorTrackingSettings.objects.create(
            team=self.team,
            project_rate_limit_value=1000,
            per_issue_rate_limit_value=None,
        )
        meta = RateLimitsRecommendation().compute(self.team)
        by_key = {r["key"]: r["enabled"] for r in meta["rate_limits"]}
        self.assertTrue(by_key["project"])
        self.assertFalse(by_key["per_issue"])

    def test_rate_limits_recommendation_ignores_other_teams_settings(self):
        other_team = self.organization.teams.create(name="other")
        ErrorTrackingSettings.objects.create(team=other_team, project_rate_limit_value=1000)
        meta = RateLimitsRecommendation().compute(self.team)
        by_key = {r["key"]: r["enabled"] for r in meta["rate_limits"]}
        self.assertFalse(by_key["project"])

    def test_rate_limits_is_completed_when_all_set(self):
        meta = {"rate_limits": [{"key": "project", "enabled": True}, {"key": "per_issue", "enabled": True}]}
        self.assertTrue(RateLimitsRecommendation().is_completed(meta))

    def test_rate_limits_is_completed_false_when_any_unset(self):
        meta = {"rate_limits": [{"key": "project", "enabled": True}, {"key": "per_issue", "enabled": False}]}
        self.assertFalse(RateLimitsRecommendation().is_completed(meta))

    def test_rate_limits_is_completed_false_when_empty(self):
        self.assertFalse(RateLimitsRecommendation().is_completed({"rate_limits": []}))

    @patch(
        "products.error_tracking.backend.logic.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute",
        return_value={"issues": []},
    )
    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_refresh_with_force_false_does_not_recompute(self, mock_alerts, mock_long_running):
        response = self._list()
        rec_id = next(r["id"] for r in response.json()["results"] if r["type"] == "long_running_issues")
        mock_long_running.reset_mock()

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/recommendations/{rec_id}/refresh/?force=false"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_long_running.assert_not_called()

    @patch(
        "products.error_tracking.backend.logic.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute",
        return_value={"issues": []},
    )
    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_refresh_with_force_true_recomputes(self, mock_alerts, mock_long_running):
        response = self._list()
        rec_id = next(r["id"] for r in response.json()["results"] if r["type"] == "long_running_issues")
        mock_long_running.reset_mock()

        response = self._refresh(rec_id)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_long_running.assert_called_once()

    @patch(
        "products.error_tracking.backend.logic.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute",
        return_value={"issues": []},
    )
    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_list_marks_recommendations_ready_after_compute(self, mock_alerts, mock_long_running):
        response = self._list()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        statuses = {r["type"]: r["status"] for r in response.json()["results"]}
        self.assertEqual(
            statuses,
            {"alerts": "ready", "long_running_issues": "ready", "rate_limits": "ready", "source_maps": "ready"},
        )
        # Each recommendation row should have been computed exactly once via the celery task path.
        self.assertEqual(mock_alerts.call_count, 1)
        self.assertEqual(mock_long_running.call_count, 1)

    @patch(
        "products.error_tracking.backend.logic.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute",
        return_value={"issues": []},
    )
    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_poll_does_not_kick_off_new_computations(self, mock_alerts, mock_long_running):
        self._list()
        mock_alerts.reset_mock()
        mock_long_running.reset_mock()

        response = self._poll()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_alerts.assert_not_called()
        mock_long_running.assert_not_called()

    def _make_frame(self, lang: str, resolved: bool, created_hours_ago: int = 1) -> ErrorTrackingStackFrame:
        frame = ErrorTrackingStackFrame.objects.create(
            team=self.team,
            raw_id=str(uuid4()),
            contents={"lang": lang},
            resolved=resolved,
        )
        ErrorTrackingStackFrame.objects.filter(id=frame.id).update(
            created_at=timezone.now() - timedelta(hours=created_hours_ago)
        )
        return frame

    def test_source_maps_compute_with_no_frames(self):
        meta = SourceMapsRecommendation().compute(self.team)

        self.assertEqual(meta["total_frames"], 0)
        self.assertEqual(meta["unresolved_frames"], 0)
        self.assertEqual(meta["unresolved_pct"], 0.0)

    def test_source_maps_compute_counts_unresolved_js_frames(self):
        for _ in range(8):
            self._make_frame(lang="javascript", resolved=True)
        for _ in range(2):
            self._make_frame(lang="javascript", resolved=False)

        meta = SourceMapsRecommendation().compute(self.team)

        self.assertEqual(meta["total_frames"], 10)
        self.assertEqual(meta["unresolved_frames"], 2)
        self.assertEqual(meta["unresolved_pct"], 0.2)

    def test_source_maps_compute_ignores_non_js_frames(self):
        self._make_frame(lang="python", resolved=False)
        self._make_frame(lang="ruby", resolved=False)
        self._make_frame(lang="javascript", resolved=True)

        meta = SourceMapsRecommendation().compute(self.team)

        self.assertEqual(meta["total_frames"], 1)
        self.assertEqual(meta["unresolved_frames"], 0)

    def test_source_maps_compute_ignores_frames_outside_lookback(self):
        self._make_frame(lang="javascript", resolved=False, created_hours_ago=48)
        self._make_frame(lang="javascript", resolved=True, created_hours_ago=1)

        meta = SourceMapsRecommendation().compute(self.team)

        self.assertEqual(meta["total_frames"], 1)
        self.assertEqual(meta["unresolved_frames"], 0)

    def test_source_maps_compute_ignores_other_teams_frames(self):
        other_team = self.organization.teams.create(name="other")
        ErrorTrackingStackFrame.objects.create(
            team=other_team,
            raw_id=str(uuid4()),
            contents={"lang": "javascript"},
            resolved=False,
        )

        meta = SourceMapsRecommendation().compute(self.team)

        self.assertEqual(meta["total_frames"], 0)

    def test_source_maps_is_completed_when_below_threshold(self):
        # 5% unresolved, threshold is 30%
        meta = {
            "total_frames": 100,
            "unresolved_frames": 5,
            "unresolved_pct": 0.05,
            "threshold_pct": 0.30,
            "min_sample_frames": 20,
        }
        self.assertTrue(SourceMapsRecommendation().is_completed(meta))

    def test_source_maps_is_completed_false_when_above_threshold(self):
        meta = {
            "total_frames": 100,
            "unresolved_frames": 45,
            "unresolved_pct": 0.45,
            "threshold_pct": 0.30,
            "min_sample_frames": 20,
        }
        self.assertFalse(SourceMapsRecommendation().is_completed(meta))

    def test_source_maps_is_completed_when_below_min_sample(self):
        # Even at 100% unresolved, with too few frames we don't fire the recommendation.
        meta = {
            "total_frames": 5,
            "unresolved_frames": 5,
            "unresolved_pct": 1.0,
            "threshold_pct": 0.30,
            "min_sample_frames": 20,
        }
        self.assertTrue(SourceMapsRecommendation().is_completed(meta))

    @patch(
        "products.error_tracking.backend.logic.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute",
        return_value={"issues": []},
    )
    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_stuck_computing_rows_are_re_kicked(self, mock_alerts, mock_long_running):
        # Simulate a worker that died mid-compute for long_running: row stays in
        # "computing" with a stale status_changed_at and never reaches "ready".
        long_running = ErrorTrackingRecommendation.objects.create(
            team=self.team,
            type="long_running_issues",
            status=ErrorTrackingRecommendation.Status.COMPUTING,
            status_changed_at=timezone.now() - timedelta(minutes=10),
        )

        self._list()

        long_running.refresh_from_db()
        self.assertEqual(long_running.status, ErrorTrackingRecommendation.Status.READY)
        mock_long_running.assert_called_once()
