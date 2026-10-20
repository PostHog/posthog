from datetime import timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework import status

from products.cdp.backend.facade.models import HogFunction
from products.error_tracking.backend.logic.recommendations.alerts import AlertsRecommendation
from products.error_tracking.backend.logic.recommendations.rate_limits import RateLimitsRecommendation
from products.error_tracking.backend.logic.recommendations.source_maps import SourceMapsRecommendation
from products.error_tracking.backend.models import (
    ErrorTrackingRecommendation,
    ErrorTrackingSettings,
    ErrorTrackingStackFrame,
)

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
MOCK_SOURCE_MAPS_META = {"total_frames": 0, "unresolved_frames": 0, "unresolved_pct": 0.0}


class TestRecommendationsAPI(APIBaseTest):
    def _list(self):
        return self.client.get(f"/api/environments/{self.team.id}/error_tracking/recommendations/")

    def _poll(self):
        return self.client.get(f"/api/environments/{self.team.id}/error_tracking/recommendations/?poll=true")

    def _dismiss(self, rec_id):
        return self.client.post(f"/api/environments/{self.team.id}/error_tracking/recommendations/{rec_id}/dismiss/")

    def _refresh(self, rec_id):
        return self.client.post(f"/api/environments/{self.team.id}/error_tracking/recommendations/{rec_id}/refresh/")

    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_first_list_creates_registered_recommendations_and_hides_unregistered_types(self, mock_alerts):
        ErrorTrackingRecommendation.objects.create(team=self.team, type="long_running_issues")

        response = self._list()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            ErrorTrackingRecommendation.objects.filter(team=self.team).exclude(type="long_running_issues").count(), 3
        )
        types = {r["type"] for r in response.json()["results"]}
        self.assertEqual(types, {"alerts", "rate_limits", "source_maps"})

    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
    )
    def test_alerts_recomputes_on_every_list(self, mock_alerts):
        mock_alerts.return_value = MOCK_ALERTS_META
        self._list()

        mock_alerts.return_value = MOCK_ALERTS_META_UPDATED
        response = self._list()

        self.assertEqual(mock_alerts.call_count, 2)
        alerts = next(r for r in response.json()["results"] if r["type"] == "alerts")
        self.assertEqual(alerts["meta"], MOCK_ALERTS_META_UPDATED)

    @patch(
        "products.error_tracking.backend.logic.recommendations.source_maps.SourceMapsRecommendation.compute",
        return_value=MOCK_SOURCE_MAPS_META,
    )
    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_source_maps_is_cached_until_interval_elapses(self, mock_alerts, mock_source_maps):
        with time_machine.travel("2026-01-01T00:00:00Z", tick=False) as frozen_time:
            self._list()
            self.assertEqual(mock_source_maps.call_count, 1)

            # Re-listing within the same refresh window doesn't recompute.
            self._list()
            self.assertEqual(mock_source_maps.call_count, 1)

            # A full refresh_interval always crosses into the next window — recompute, regardless of phase.
            frozen_time.shift(SourceMapsRecommendation.refresh_interval)
            self._list()
            self.assertEqual(mock_source_maps.call_count, 2)

    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_dismiss_persists_across_requests(self, mock_alerts):
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
        "products.error_tracking.backend.logic.recommendations.source_maps.SourceMapsRecommendation.compute",
        return_value=MOCK_SOURCE_MAPS_META,
    )
    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_refresh_with_force_false_does_not_recompute(self, mock_alerts, mock_source_maps):
        response = self._list()
        rec_id = next(r["id"] for r in response.json()["results"] if r["type"] == "source_maps")
        mock_source_maps.reset_mock()

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/recommendations/{rec_id}/refresh/?force=false"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_source_maps.assert_not_called()

    @patch(
        "products.error_tracking.backend.logic.recommendations.source_maps.SourceMapsRecommendation.compute",
        return_value=MOCK_SOURCE_MAPS_META,
    )
    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_refresh_with_force_true_recomputes(self, mock_alerts, mock_source_maps):
        response = self._list()
        rec_id = next(r["id"] for r in response.json()["results"] if r["type"] == "source_maps")
        mock_source_maps.reset_mock()

        response = self._refresh(rec_id)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_source_maps.assert_called_once()

    @patch(
        "products.error_tracking.backend.logic.recommendations.source_maps.SourceMapsRecommendation.compute",
        return_value=MOCK_SOURCE_MAPS_META,
    )
    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_list_marks_recommendations_ready_after_compute(self, mock_alerts, mock_source_maps):
        response = self._list()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        statuses = {r["type"]: r["status"] for r in response.json()["results"]}
        self.assertEqual(statuses, {"alerts": "ready", "rate_limits": "ready", "source_maps": "ready"})
        # Each recommendation row should have been computed exactly once via the celery task path.
        self.assertEqual(mock_alerts.call_count, 1)
        self.assertEqual(mock_source_maps.call_count, 1)

    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_poll_does_not_kick_off_new_computations(self, mock_alerts):
        self._list()
        mock_alerts.reset_mock()

        response = self._poll()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_alerts.assert_not_called()

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
        "products.error_tracking.backend.logic.recommendations.source_maps.SourceMapsRecommendation.compute",
        return_value=MOCK_SOURCE_MAPS_META,
    )
    @patch(
        "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_stuck_computing_rows_are_re_kicked(self, mock_alerts, mock_source_maps):
        # Simulate a worker that died mid-compute for source_maps: row stays in
        # "computing" with a stale status_changed_at and never reaches "ready".
        source_maps = ErrorTrackingRecommendation.objects.create(
            team=self.team,
            type="source_maps",
            status=ErrorTrackingRecommendation.Status.COMPUTING,
            status_changed_at=timezone.now() - timedelta(minutes=10),
        )

        self._list()

        source_maps.refresh_from_db()
        self.assertEqual(source_maps.status, ErrorTrackingRecommendation.Status.READY)
        mock_source_maps.assert_called_once()
