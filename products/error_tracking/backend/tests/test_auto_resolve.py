from datetime import timedelta
from uuid import UUID

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.utils import uuid7

from products.error_tracking.backend.logic.auto_resolve import (
    TeamAutoResolveSetting,
    auto_resolve_team,
    get_auto_resolve_team_settings,
)
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingSettings,
)
from products.error_tracking.backend.temporal.auto_resolve.activities import auto_resolve_batch_activity
from products.error_tracking.backend.temporal.auto_resolve.types import (
    AutoResolveBatchInputs,
    AutoResolveBatchResult,
    TeamAutoResolveConfig,
)


class TestAutoResolve(ClickhouseTestMixin, BaseTest):
    def _create_issue(
        self,
        *,
        last_state_change_days_ago: int,
        status: str = ErrorTrackingIssue.Status.ACTIVE,
        fingerprints: int = 1,
        issue_id: UUID | None = None,
    ) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(
            id=issue_id or uuid7(), team=self.team, status=status, name="TypeError"
        )
        ErrorTrackingIssue.objects.filter(id=issue.id).update(
            created_at=timezone.now() - timedelta(days=60),
            state_updated_at=timezone.now() - timedelta(days=last_state_change_days_ago),
            last_received_at=timezone.now() - timedelta(days=last_state_change_days_ago),
        )
        for i in range(fingerprints):
            ErrorTrackingIssueFingerprintV2.objects.create(
                team=self.team, issue=issue, fingerprint=f"fp::{issue.id}::{i}"
            )
        issue.refresh_from_db()
        return issue

    def _create_exception(self, fingerprint: str, days_ago: int) -> None:
        _create_event(
            distinct_id="user_1",
            event="$exception",
            team=self.team,
            properties={"$exception_fingerprint": fingerprint},
            timestamp=(timezone.now() - timedelta(days=days_ago)).isoformat(),
        )

    def _run(self, days: int = 3) -> int:
        ErrorTrackingSettings.objects.update_or_create(team=self.team, defaults={"auto_resolve_after_days": days})
        with self.captureOnCommitCallbacks(execute=True):
            return auto_resolve_team(self.team.id)

    def test_resolves_quiet_issue_as_system_and_keeps_recently_seen_issue(self) -> None:
        quiet = self._create_issue(last_state_change_days_ago=10)
        self._create_exception(f"fp::{quiet.id}::0", days_ago=5)
        noisy = self._create_issue(last_state_change_days_ago=10, fingerprints=2)
        # Only the issue's second fingerprint fired recently; that still counts as activity.
        self._create_exception(f"fp::{noisy.id}::1", days_ago=1)
        flush_persons_and_events()

        with patch("products.error_tracking.backend.logic.lifecycle_events.produce_internal_event") as mock_produce:
            resolved = self._run(days=3)

        assert resolved == 1
        quiet.refresh_from_db()
        noisy.refresh_from_db()
        assert quiet.status == ErrorTrackingIssue.Status.RESOLVED
        assert noisy.status == ErrorTrackingIssue.Status.ACTIVE

        log = ActivityLog.objects.get(scope="ErrorTrackingIssue", activity="updated", item_id=str(quiet.id))
        assert log.is_system is True
        assert log.user is None

        event = mock_produce.call_args.kwargs["event"]
        assert event.event == "$error_tracking_issue_resolved"
        assert event.properties["resolved_reason"] == "inactivity"

    @parameterized.expand(
        [
            # Reactivated two days ago: give it the full window before judging it.
            ("recent_state_change", ErrorTrackingIssue.Status.ACTIVE, 2, 1),
            ("suppressed", ErrorTrackingIssue.Status.SUPPRESSED, 10, 1),
            ("already_resolved", ErrorTrackingIssue.Status.RESOLVED, 10, 1),
            ("missing_fingerprints", ErrorTrackingIssue.Status.ACTIVE, 10, 0),
        ]
    )
    def test_leaves_ineligible_issues_untouched(
        self, _name: str, status: str, last_state_change_days_ago: int, fingerprints: int
    ) -> None:
        issue = self._create_issue(
            status=status, last_state_change_days_ago=last_state_change_days_ago, fingerprints=fingerprints
        )
        flush_persons_and_events()

        assert self._run(days=3) == 0
        issue.refresh_from_db()
        assert issue.status == status

    @parameterized.expand([("saved_cursor", False), ("lost_cursor", True)])
    def test_sweeps_progress_past_noisy_issues_and_wrap(self, _name: str, lose_cursor: bool) -> None:
        noisy = self._create_issue(last_state_change_days_ago=10, issue_id=UUID(int=1))
        quiet = self._create_issue(last_state_change_days_ago=10, issue_id=UUID(int=2))
        self._create_exception(f"fp::{noisy.id}::0", days_ago=1)
        flush_persons_and_events()

        with patch("products.error_tracking.backend.logic.auto_resolve.MAX_ISSUES_PER_TEAM_RUN", 1):
            assert self._run() == 0
            if lose_cursor:
                cache.clear()
                assert self._run() == 0
            assert self._run() == 1
            quiet.refresh_from_db()
            noisy.refresh_from_db()
            assert quiet.status == ErrorTrackingIssue.Status.RESOLVED
            assert noisy.status == ErrorTrackingIssue.Status.ACTIVE

            with time_machine.travel(timezone.now() + timedelta(days=4), tick=False):
                assert self._run() == 1
                noisy.refresh_from_db()
                assert noisy.status == ErrorTrackingIssue.Status.RESOLVED
                assert self._run() == 0

    def test_failed_page_is_retried_before_later_issues(self) -> None:
        first = self._create_issue(last_state_change_days_ago=10, issue_id=UUID(int=1))
        second = self._create_issue(last_state_change_days_ago=10, issue_id=UUID(int=2))
        flush_persons_and_events()

        with patch("products.error_tracking.backend.logic.auto_resolve.MAX_ISSUES_PER_TEAM_RUN", 1):
            with patch(
                "products.error_tracking.backend.logic.auto_resolve.sync_execute",
                side_effect=RuntimeError("unavailable"),
            ):
                with self.assertRaisesRegex(RuntimeError, "unavailable"):
                    self._run()
            assert self._run() == 1
            first.refresh_from_db()
            second.refresh_from_db()
            assert first.status == ErrorTrackingIssue.Status.RESOLVED
            assert second.status == ErrorTrackingIssue.Status.ACTIVE

    @time_machine.travel(timezone.now, tick=False)
    def test_reactivation_during_exception_query_stays_active(self) -> None:
        issue = self._create_issue(last_state_change_days_ago=10)

        def reactivate(*args: object, **kwargs: object) -> list[tuple[str]]:
            ErrorTrackingIssue.objects.filter(id=issue.id).update(state_updated_at=timezone.now())
            return []

        with patch("products.error_tracking.backend.logic.auto_resolve.sync_execute", side_effect=reactivate):
            assert self._run() == 0

        issue.refresh_from_db()
        assert issue.status == ErrorTrackingIssue.Status.ACTIVE
        assert not ActivityLog.objects.filter(scope="ErrorTrackingIssue", item_id=str(issue.id)).exists()

    @time_machine.travel(timezone.now, tick=False)
    def test_opted_in_and_pending_sync_teams_are_swept(self) -> None:
        ErrorTrackingSettings.objects.create(team=self.team, auto_resolve_after_days=7)
        disabled = Team.objects.create(organization=self.organization)
        ErrorTrackingSettings.objects.create(team=disabled)
        missing_settings = Team.objects.create(organization=self.organization)
        ErrorTrackingSettings.objects.create(team=Team.objects.create(organization=self.organization))
        for team in [disabled, missing_settings, disabled]:
            ErrorTrackingIssue.objects.create(
                team=team,
                status=ErrorTrackingIssue.Status.RESOLVED,
                auto_resolve_sync_requested_at=timezone.now(),
            )

        assert get_auto_resolve_team_settings() == [
            TeamAutoResolveSetting(team_id=self.team.id, days=7),
            TeamAutoResolveSetting(team_id=disabled.id, days=None),
            TeamAutoResolveSetting(team_id=missing_settings.id, days=None),
        ]

    def test_new_higher_ids_do_not_prevent_revisiting_older_issues(self) -> None:
        older = self._create_issue(last_state_change_days_ago=10, issue_id=UUID(int=1))
        self._create_issue(last_state_change_days_ago=10, issue_id=UUID(int=2))
        self._create_exception(f"fp::{older.id}::0", days_ago=1)
        flush_persons_and_events()

        with patch("products.error_tracking.backend.logic.auto_resolve.MAX_ISSUES_PER_TEAM_RUN", 1):
            assert self._run() == 0
            self._create_issue(last_state_change_days_ago=10, issue_id=UUID(int=3))
            assert self._run() == 1
            self._create_issue(last_state_change_days_ago=10, issue_id=UUID(int=4))
            with time_machine.travel(timezone.now() + timedelta(days=4), tick=False):
                assert self._run() == 1
            older.refresh_from_db()
            assert older.status == ErrorTrackingIssue.Status.RESOLVED

    @parameterized.expand([("disabled", None), ("increased", 30), ("deleted", None)])
    def test_batch_reloads_settings_after_enumeration(self, name: str, days: int | None) -> None:
        issue = self._create_issue(last_state_change_days_ago=10)
        ErrorTrackingSettings.objects.create(team=self.team, auto_resolve_after_days=3)
        team_settings = get_auto_resolve_team_settings()
        inputs = AutoResolveBatchInputs(
            teams=[TeamAutoResolveConfig(team_id=setting.team_id, days=setting.days) for setting in team_settings]
        )
        if name == "deleted":
            ErrorTrackingSettings.objects.filter(team=self.team).delete()
        else:
            ErrorTrackingSettings.objects.filter(team=self.team).update(auto_resolve_after_days=days)

        with (
            patch("products.error_tracking.backend.temporal.auto_resolve.activities.close_old_connections"),
            patch("products.error_tracking.backend.temporal.auto_resolve.activities.activity.heartbeat"),
        ):
            assert auto_resolve_batch_activity(inputs) == AutoResolveBatchResult(
                teams_processed=1, teams_failed=0, issues_resolved=0
            )
        issue.refresh_from_db()
        assert issue.status == ErrorTrackingIssue.Status.ACTIVE

    @parameterized.expand([("disabled", None), ("increased", 30), ("deleted", None)])
    def test_setting_change_during_exception_query_stays_active(self, name: str, days: int | None) -> None:
        issue = self._create_issue(last_state_change_days_ago=10)

        def change_setting(*args: object, **kwargs: object) -> list[tuple[str]]:
            if name == "deleted":
                ErrorTrackingSettings.objects.filter(team=self.team).delete()
            else:
                ErrorTrackingSettings.objects.filter(team=self.team).update(auto_resolve_after_days=days)
            return []

        with patch("products.error_tracking.backend.logic.auto_resolve.sync_execute", side_effect=change_setting):
            assert self._run() == 0
        issue.refresh_from_db()
        assert issue.status == ErrorTrackingIssue.Status.ACTIVE
        assert not ActivityLog.objects.filter(scope="ErrorTrackingIssue", item_id=str(issue.id)).exists()

    @parameterized.expand([("recent_receipt", False), ("unknown_receipt", True)])
    @time_machine.travel(timezone.now, tick=False)
    def test_old_event_does_not_override_receipt_grace_period(self, _name: str, unknown_receipt: bool) -> None:
        issue = self._create_issue(last_state_change_days_ago=10)
        self._create_exception(f"fp::{issue.id}::0", days_ago=10)
        flush_persons_and_events()
        ErrorTrackingIssue.objects.filter(team=self.team, id=issue.id).update(
            last_received_at=None if unknown_receipt else timezone.now()
        )

        assert self._run() == 0
        issue.refresh_from_db()
        assert issue.status == ErrorTrackingIssue.Status.ACTIVE

    @parameterized.expand(
        [("inside_cache_window", 59, 0), ("cache_window_boundary", 60, 0), ("outside_cache_window", 61, 1)]
    )
    def test_receipt_cache_grace_period(self, _name: str, seconds: int, expected_resolved: int) -> None:
        with time_machine.travel(timezone.now(), tick=False):
            issue = self._create_issue(last_state_change_days_ago=10)
            ErrorTrackingIssue.objects.filter(team=self.team, id=issue.id).update(
                last_received_at=timezone.now() - timedelta(days=3, seconds=seconds)
            )
            with patch("products.error_tracking.backend.logic.auto_resolve.sync_execute", return_value=[]):
                assert self._run() == expected_resolved
            issue.refresh_from_db()
            assert issue.status == (
                ErrorTrackingIssue.Status.RESOLVED if expected_resolved else ErrorTrackingIssue.Status.ACTIVE
            )

    @time_machine.travel(timezone.now, tick=False)
    def test_receipt_during_exception_query_stays_active(self) -> None:
        issue = self._create_issue(last_state_change_days_ago=10)

        def receive_event(*args: object, **kwargs: object) -> list[tuple[str]]:
            ErrorTrackingIssue.objects.filter(team=self.team, id=issue.id).update(last_received_at=timezone.now())
            return []

        with patch("products.error_tracking.backend.logic.auto_resolve.sync_execute", side_effect=receive_event):
            assert self._run() == 0
        issue.refresh_from_db()
        assert issue.status == ErrorTrackingIssue.Status.ACTIVE
        assert not ActivityLog.objects.filter(scope="ErrorTrackingIssue", item_id=str(issue.id)).exists()

    def test_batch_continues_after_a_team_fails(self) -> None:
        teams = [TeamAutoResolveConfig(team_id=1, days=3), TeamAutoResolveConfig(team_id=2, days=3)]

        with (
            patch("products.error_tracking.backend.temporal.auto_resolve.activities.close_old_connections"),
            patch("products.error_tracking.backend.temporal.auto_resolve.activities.activity.heartbeat"),
            patch(
                "products.error_tracking.backend.temporal.auto_resolve.activities.auto_resolve_team",
                side_effect=[RuntimeError("clickhouse down"), 4],
            ),
        ):
            result = auto_resolve_batch_activity(AutoResolveBatchInputs(teams=teams))

        assert result == AutoResolveBatchResult(teams_processed=1, teams_failed=1, issues_resolved=4)
