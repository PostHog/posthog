from datetime import timedelta
from uuid import uuid4

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.utils import timezone

from rest_framework import status

from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.utils import uuid7

from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingRecommendation,
    sync_issues_to_clickhouse,
)
from products.error_tracking.backend.recommendations.alerts import AlertsRecommendation
from products.error_tracking.backend.recommendations.long_running_issues import LongRunningIssuesRecommendation

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


class TestRecommendationsAPI(ClickhouseTestMixin, APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        materialize("events", "$exception_issue_id", is_nullable=True)

    def _list(self):
        return self.client.get(f"/api/environments/{self.team.id}/error_tracking/recommendations/")

    def _dismiss(self, rec_id):
        return self.client.post(f"/api/environments/{self.team.id}/error_tracking/recommendations/{rec_id}/dismiss/")

    def _refresh(self, rec_id):
        return self.client.post(f"/api/environments/{self.team.id}/error_tracking/recommendations/{rec_id}/refresh/")

    @patch(
        "products.error_tracking.backend.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute",
        return_value={"issues": []},
    )
    @patch(
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_first_list_creates_both_recommendations(self, mock_alerts, mock_long_running):
        self.assertEqual(ErrorTrackingRecommendation.objects.filter(team=self.team).count(), 0)

        response = self._list()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(ErrorTrackingRecommendation.objects.filter(team=self.team).count(), 2)
        types = {r["type"] for r in response.json()["results"]}
        self.assertEqual(types, {"alerts", "long_running_issues"})

    @patch(
        "products.error_tracking.backend.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute",
        return_value={"issues": []},
    )
    @patch(
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
    )
    def test_alerts_recomputes_on_every_list(self, mock_alerts, mock_long_running):
        mock_alerts.return_value = MOCK_ALERTS_META
        self._list()

        mock_alerts.return_value = MOCK_ALERTS_META_UPDATED
        response = self._list()

        self.assertEqual(mock_alerts.call_count, 2)
        alerts = next(r for r in response.json()["results"] if r["type"] == "alerts")
        self.assertEqual(alerts["meta"], MOCK_ALERTS_META_UPDATED)

    @freeze_time("2026-01-01T00:00:00Z", as_kwarg="frozen_time")
    @patch(
        "products.error_tracking.backend.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute",
    )
    @patch(
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_long_running_is_cached_until_interval_elapses(self, mock_alerts, mock_long_running, frozen_time):
        mock_long_running.return_value = {"issues": []}
        self._list()
        self.assertEqual(mock_long_running.call_count, 1)

        frozen_time.tick(timedelta(minutes=30))
        self._list()
        self.assertEqual(mock_long_running.call_count, 1)

        frozen_time.tick(timedelta(hours=1))
        self._list()
        self.assertEqual(mock_long_running.call_count, 2)

    @patch(
        "products.error_tracking.backend.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute",
        return_value={"issues": []},
    )
    @patch(
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
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

    def test_long_running_limits_to_ten(self):
        for i in range(15):
            issue = self._create_issue(
                created_at=timezone.now() - timedelta(days=60 - i),
                name=f"Issue {i:02d}",
            )
            self._create_exception(issue.id, _days_ago(1))
        flush_persons_and_events()

        meta = LongRunningIssuesRecommendation().compute(self.team)

        self.assertEqual(len(meta["issues"]), 10)
        self.assertEqual(meta["issues"][0]["name"], "Issue 00")
        self.assertEqual(meta["issues"][9]["name"], "Issue 09")

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

    @patch(
        "products.error_tracking.backend.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute",
        return_value={"issues": []},
    )
    @patch(
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
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
        "products.error_tracking.backend.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute",
        return_value={"issues": []},
    )
    @patch(
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    def test_refresh_with_force_true_recomputes(self, mock_alerts, mock_long_running):
        response = self._list()
        rec_id = next(r["id"] for r in response.json()["results"] if r["type"] == "long_running_issues")
        mock_long_running.reset_mock()

        response = self._refresh(rec_id)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_long_running.assert_called_once()
