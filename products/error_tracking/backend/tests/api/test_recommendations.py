from datetime import timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition, Team

from products.access_control.backend.facade.api import upsert_property_access_control
from products.access_control.backend.facade.contracts import PropertyAccessLevel, UpsertPropertyAccessControlInput
from products.cdp.backend.facade.models import HogFunction
from products.error_tracking.backend.logic.recommendations.alerts import AlertsRecommendation
from products.error_tracking.backend.logic.recommendations.rate_limits import RateLimitsRecommendation
from products.error_tracking.backend.logic.recommendations.source_maps import SourceMapsRecommendation
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingRecommendation,
    ErrorTrackingSettings,
    ErrorTrackingStackFrame,
    ErrorTrackingSymbolSet,
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


class _StackFrameFactory:
    team: Team

    def _make_frame(
        self,
        contents: dict | None = None,
        resolved: bool = False,
        with_symbol_set: bool = False,
        created_hours_ago: int = 1,
        team: Team | None = None,
    ) -> ErrorTrackingStackFrame:
        team = team or self.team
        symbol_set = (
            ErrorTrackingSymbolSet.objects.create(team=team, ref=str(uuid4()), storage_ptr=str(uuid4()))
            if with_symbol_set
            else None
        )
        frame = ErrorTrackingStackFrame.objects.create(
            team=team,
            raw_id=str(uuid4()),
            contents={"lang": "javascript", **(contents or {})},
            resolved=resolved,
            symbol_set=symbol_set,
        )
        ErrorTrackingStackFrame.objects.filter(id=frame.id).update(
            created_at=timezone.now() - timedelta(hours=created_hours_ago)
        )
        return frame

    def _make_missing_symbols_frame(self, **kwargs) -> ErrorTrackingStackFrame:
        return self._make_frame(
            contents={"resolve_failure": "No sourcemap uploaded for chunk id: 0f1e2d", "column": 4321}, **kwargs
        )


class TestRecommendationsAPI(_StackFrameFactory, APIBaseTest):
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

    def test_source_maps_compute_with_no_frames(self):
        meta = SourceMapsRecommendation().compute(self.team)

        self.assertEqual(meta["total_frames"], 0)
        self.assertEqual(meta["unresolved_frames"], 0)
        self.assertEqual(meta["unresolved_pct"], 0.0)

    def test_source_maps_compute_counts_frames_missing_symbols_among_frames_that_need_them(self):
        for _ in range(8):
            self._make_frame(resolved=True, with_symbol_set=True)
        for _ in range(2):
            self._make_missing_symbols_frame()
        self._make_frame(contents={"line": 12, "column": 4321}, resolved=True)
        self._make_frame(contents={"lang": "python"}, resolved=True)
        self._make_frame(contents={"line": 12}, resolved=True)
        self._make_frame(resolved=True)
        self._make_frame(
            contents={"resolve_failure": "Could not find sourcemap for source url: https://example.com/app.js"},
            resolved=True,
            with_symbol_set=True,
        )

        meta = SourceMapsRecommendation().compute(self.team)

        self.assertEqual(meta["platform"], "javascript")
        self.assertEqual(meta["total_frames"], 11)
        self.assertEqual(meta["unresolved_frames"], 2)
        self.assertEqual(meta["unresolved_pct"], 2 / 11)

    @parameterized.expand(
        [
            (
                "chunk_id_without_upload",
                {"resolve_failure": "No sourcemap uploaded for chunk id: 0f1e2d", "column": 4321},
                True,
            ),
            (
                "script_without_source_map",
                {"resolve_failure": "Could not find sourcemap for source url: https://example.com/app.js"},
                True,
            ),
            (
                "source_map_not_found",
                {"resolve_failure": "HTTP error 404 while fetching: https://example.com/app.js.map"},
                True,
            ),
            (
                "source_map_url_serves_html",
                {"resolve_failure": "Invalid source map: expected value at line 1 column 1"},
                True,
            ),
            (
                "source_map_over_fetch_limit",
                {
                    "resolve_failure": "Network error while fetching: Response from https://example.com/app.js.map exceeded the 25000000 byte limit"
                },
                True,
            ),
            (
                "hermes_bundle_without_chunk_id",
                {"resolve_failure": "No chunk id sent with frame", "column": 1234, "source": "index.android.bundle"},
                True,
            ),
            (
                "proguard_map_missing",
                {"lang": "java", "module": "a.b.c", "resolve_failure": "No proguard map uploaded for id: 5d2c"},
                True,
            ),
            (
                "dsym_missing_for_app_code",
                {
                    "lang": "swift",
                    "in_app": True,
                    "module": "Example",
                    "resolve_failure": "No dSYM uploaded for debug_id: 8a9b-11",
                },
                True,
            ),
            (
                "dsym_missing_for_frame_without_module",
                {"lang": "swift", "in_app": True, "resolve_failure": "No dSYM uploaded for debug_id: 8a9b-11"},
                True,
            ),
            (
                "debug_symbols_missing_for_app_code",
                {"lang": "rust", "in_app": True, "resolve_failure": "No debug symbols uploaded for debug_id: 8a9b-11"},
                True,
            ),
            (
                "private_ip_address",
                {"resolve_failure": "Refusing to fetch from non-public address: http://127.0.0.1:5173/app.js"},
                False,
            ),
            (
                "localhost_unreachable",
                {
                    "resolve_failure": "Network error while fetching: error sending request for url (http://localhost:3000/app.js)"
                },
                False,
            ),
            ("timeout", {"resolve_failure": "Request timed out while fetching: https://example.com/app.js"}, False),
            ("server_error", {"resolve_failure": "HTTP error 503 while fetching: https://example.com/app.js"}, False),
            ("rate_limited", {"resolve_failure": "HTTP error 429 while fetching: https://example.com/app.js"}, False),
            (
                "localhost_refused_by_egress_proxy",
                {"resolve_failure": "HTTP error 407 while fetching: http://localhost:3000/app.js"},
                False,
            ),
            ("bad_request", {"resolve_failure": "HTTP error 400 while fetching: https://example.com/gtm.js"}, False),
            ("unparseable_source_map_url", {"resolve_failure": "Invalid source url: https://[bad"}, False),
            ("source_map_without_token", {"resolve_failure": "Token not found for frame: a:1:5021"}, False),
            (
                "hermes_internal_bytecode",
                {"resolve_failure": "No chunk id sent with frame", "column": 12, "source": "InternalBytecode.js"},
                False,
            ),
            (
                "hermes_frame_without_column",
                {"resolve_failure": "No chunk id sent with frame", "source": "native"},
                False,
            ),
            (
                "chunk_id_without_upload_or_column",
                {"resolve_failure": "No sourcemap uploaded for chunk id: 0f1e2d", "source": "index.android.bundle"},
                False,
            ),
            (
                "hermes_metro_dev_server_bundle",
                {
                    "resolve_failure": "No chunk id sent with frame",
                    "column": 17,
                    "source": "http://localhost:8081/index.bundle?platform=ios&dev=true",
                },
                False,
            ),
            (
                "android_framework_class",
                {
                    "lang": "java",
                    "module": "android.os.Handler",
                    "resolve_failure": "No proguard map uploaded for id: 5d2c",
                },
                False,
            ),
            (
                "dsym_missing_for_system_framework",
                {"lang": "swift", "in_app": False, "resolve_failure": "No dSYM uploaded for debug_id: 8a9b-11"},
                False,
            ),
            (
                "dsym_missing_for_xcode_debug_build",
                {
                    "lang": "swift",
                    "in_app": True,
                    "module": "Example.debug.dylib",
                    "resolve_failure": "No dSYM uploaded for debug_id: 8a9b-11",
                },
                False,
            ),
            (
                "native_frame_already_readable",
                {
                    "lang": "go",
                    "in_app": True,
                    "line": 42,
                    "resolved_name": "main.handler",
                    "resolve_failure": "No debug symbols uploaded for debug_id: 8a9b-11",
                },
                False,
            ),
        ]
    )
    def test_source_maps_compute_counts_only_failures_an_upload_fixes(self, _name, contents, counted):
        self._make_frame(contents=contents)

        meta = SourceMapsRecommendation().compute(self.team)

        self.assertEqual(meta["unresolved_frames"], 1 if counted else 0)
        self.assertEqual(meta["total_frames"], 1 if counted else 0)

    def test_source_maps_compute_scores_each_platform_on_its_own(self):
        for _ in range(100):
            self._make_frame(contents={"lang": "java"}, resolved=True, with_symbol_set=True)
        for _ in range(25):
            self._make_missing_symbols_frame()
        for _ in range(5):
            self._make_frame(resolved=True, with_symbol_set=True)

        recommendation = SourceMapsRecommendation()
        meta = recommendation.compute(self.team)

        self.assertEqual(meta["platform"], "javascript")
        self.assertEqual((meta["total_frames"], meta["unresolved_frames"]), (30, 25))
        self.assertEqual(meta["platforms"]["java"]["total_frames"], 100)
        self.assertFalse(recommendation.is_completed(meta))

    def test_source_maps_compute_ignores_frames_outside_lookback(self):
        self._make_missing_symbols_frame(created_hours_ago=48)
        self._make_frame(resolved=True, with_symbol_set=True, created_hours_ago=1)

        meta = SourceMapsRecommendation().compute(self.team)

        self.assertEqual(meta["total_frames"], 1)
        self.assertEqual(meta["unresolved_frames"], 0)

    def test_source_maps_compute_ignores_other_teams_frames(self):
        self._make_missing_symbols_frame(team=self.organization.teams.create(name="other"))

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


CHUNK_NOT_UPLOADED = "No sourcemap uploaded for chunk id: 0f1e2d"
NOT_FOUND = (
    "HTTP error 404 while fetching: HTTP status client error (404 Not Found) for url (https://example.com/app.js.map)"
)


class TestSourceMapsExamplesAPI(_StackFrameFactory, ClickhouseTestMixin, APIBaseTest):
    def _issue(self, description: str, fingerprint: str) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="TypeError", description=description)
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)
        return issue

    def _exception(self, fingerprint: str, value: str, frames: list[ErrorTrackingStackFrame]) -> None:
        _create_event(
            event="$exception",
            team=self.team,
            distinct_id="user",
            properties={
                "$exception_fingerprint": fingerprint,
                "$exception_list": [
                    {
                        "type": "TypeError",
                        "value": value,
                        "stacktrace": {
                            "type": "resolved",
                            "frames": [
                                {"raw_id": f"{frame.raw_id}/{frame.part}", "resolved": frame.resolved, **frame.contents}
                                for frame in frames
                            ],
                        },
                    }
                ],
            },
        )

    @time_machine.travel("2026-10-20T12:00:00Z", tick=False)
    def test_source_maps_examples_group_missing_frames_with_the_exceptions_they_appear_in(self):
        chunk_contents = {
            "resolve_failure": CHUNK_NOT_UPLOADED,
            "source": "/assets/app.js",
            "mangled_name": "e",
            "line": 1,
            "column": 4321,
            "in_app": True,
        }
        # The examples search the 20 newest frames of each file, so the frame in the exceptions is the newest.
        crash_frame = self._make_frame(contents=chunk_contents)
        for _ in range(20):
            self._make_frame(contents=chunk_contents, created_hours_ago=2)
        not_found_frames = [
            self._make_frame(contents={"resolve_failure": NOT_FOUND, "source": "/app.js"}) for _ in range(2)
        ]
        entry = self._make_frame(
            contents={"source": "src/main.ts", "resolved_name": "main", "line": 3, "in_app": True},
            resolved=True,
            with_symbol_set=True,
        )
        self._make_frame(contents={"resolve_failure": "Request timed out while fetching: https://example.com/b.js"})
        for module in ("a.b", "a.c"):
            self._make_frame(
                contents={"lang": "java", "module": module, "resolve_failure": "No proguard map uploaded for id: 5d2c"}
            )
        type_error = self._issue("Cannot read properties of undefined", "fp-type-error")
        fetch_error = self._issue("Failed to fetch", "fp-fetch-error")
        for _ in range(2):
            self._exception("fp-type-error", "Cannot read properties of undefined", [entry, crash_frame])
        self._exception("fp-fetch-error", "Failed to fetch", [not_found_frames[0]])
        self._exception("fp-unrelated", "Unrelated", [entry])

        base = f"/api/environments/{self.team.id}/error_tracking/recommendations/source_maps_examples/"
        # A default row limit of 1 fails the test when a query relies on HogQL's default limit.
        with patch("posthog.hogql.constants.DEFAULT_RETURNED_ROWS", 1):
            javascript = self.client.get(f"{base}?platform=javascript")
            java = self.client.get(f"{base}?platform=java")

        self.assertEqual(javascript.status_code, status.HTTP_200_OK)
        self.assertEqual(
            javascript.json(),
            {
                "platform": "javascript",
                "lookback_hours": 24,
                "exceptions_loaded": True,
                "results": [
                    {
                        "reason": "chunk_not_uploaded",
                        "location": "/assets/app.js",
                        "symbol_id": "0f1e2d",
                        "http_status": None,
                        "frames": 21,
                        "issues": [
                            {
                                "id": str(type_error.id),
                                "name": "TypeError",
                                "description": "Cannot read properties of undefined",
                                "occurrences": 2,
                            }
                        ],
                        "issue_count": 1,
                        "issue_count_capped": True,
                        "example_exception": {
                            "issue_id": str(type_error.id),
                            "fingerprint": "fp-type-error",
                            "timestamp": "2026-10-20T12:00:00Z",
                            "type": "TypeError",
                            "value": "Cannot read properties of undefined",
                            "frames": [
                                {
                                    "function": "e",
                                    "source": "/assets/app.js",
                                    "line": 1,
                                    "column": 4321,
                                    "in_app": True,
                                    "missing_symbols": True,
                                },
                                {
                                    "function": "main",
                                    "source": "src/main.ts",
                                    "line": 3,
                                    "column": None,
                                    "in_app": True,
                                    "missing_symbols": False,
                                },
                            ],
                        },
                    },
                    {
                        "reason": "file_not_reachable",
                        "location": "https://example.com/app.js.map",
                        "symbol_id": None,
                        "http_status": 404,
                        "frames": 2,
                        "issues": [
                            {
                                "id": str(fetch_error.id),
                                "name": "TypeError",
                                "description": "Failed to fetch",
                                "occurrences": 1,
                            }
                        ],
                        "issue_count": 1,
                        "issue_count_capped": False,
                        "example_exception": {
                            "issue_id": str(fetch_error.id),
                            "fingerprint": "fp-fetch-error",
                            "timestamp": "2026-10-20T12:00:00Z",
                            "type": "TypeError",
                            "value": "Failed to fetch",
                            "frames": [
                                {
                                    "function": None,
                                    "source": "/app.js",
                                    "line": None,
                                    "column": None,
                                    "in_app": False,
                                    "missing_symbols": True,
                                }
                            ],
                        },
                    },
                ],
            },
        )
        self.assertEqual(
            [(r["reason"], r["symbol_id"], r["frames"], r["issues"]) for r in java.json()["results"]],
            [("mapping_not_uploaded", "5d2c", 2, [])],
        )

    def test_source_maps_examples_hide_exceptions_from_a_user_who_cannot_read_the_exception_list(self):
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        exception_list = PropertyDefinition.objects.create(
            team=self.team, name="$exception_list", type=PropertyDefinition.Type.EVENT
        )
        upsert_property_access_control(
            team_id=self.team.id,
            created_by_id=self.user.id,
            input=UpsertPropertyAccessControlInput(
                access_level=PropertyAccessLevel.NONE,
                property_definition_id=str(exception_list.id),
                organization_member_id=self.organization_membership.id,
            ),
        )
        frame = self._make_frame(
            contents={"resolve_failure": CHUNK_NOT_UPLOADED, "source": "/assets/app.js", "column": 4321}
        )
        self._issue("Cannot read properties of undefined", "fp-type-error")
        self._exception("fp-type-error", "Cannot read properties of undefined", [frame])
        flush_persons_and_events()

        response = self.client.get(
            f"/api/environments/{self.team.id}/error_tracking/recommendations/source_maps_examples/?platform=javascript"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [
                (r["frames"], r["location"], r["symbol_id"], r["issues"], r["issue_count"], r["example_exception"])
                for r in response.json()["results"]
            ],
            [(1, None, None, [], 0, None)],
        )
