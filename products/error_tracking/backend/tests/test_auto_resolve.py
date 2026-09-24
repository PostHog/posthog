from datetime import timedelta
from uuid import UUID

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db.models.signals import pre_save
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.utils import uuid7

from products.error_tracking.backend.logic.auto_resolve import auto_resolve_team, get_auto_resolve_team_ids
from products.error_tracking.backend.logic.issue_mutations import update_issue
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingSettings,
)
from products.error_tracking.backend.temporal.auto_resolve.activities import auto_resolve_batch_activity
from products.error_tracking.backend.temporal.auto_resolve.types import AutoResolveBatchInputs, AutoResolveBatchResult


class TestAutoResolve(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("products.error_tracking.backend.models.ClickhouseProducer"))

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

    def _run(self, days: int = 3) -> int:
        ErrorTrackingSettings.objects.update_or_create(team=self.team, defaults={"auto_resolve_after_days": days})
        with self.captureOnCommitCallbacks(execute=True):
            return auto_resolve_team(self.team.id)

    def test_resolves_quiet_issue_as_system_and_keeps_recently_seen_issue(self) -> None:
        quiet = self._create_issue(last_state_change_days_ago=10)
        noisy = self._create_issue(last_state_change_days_ago=10, fingerprints=2)
        ErrorTrackingIssue.objects.filter(id=noisy.id).update(last_received_at=timezone.now())

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

        assert self._run(days=3) == 0
        issue.refresh_from_db()
        assert issue.status == status

    def test_bounded_sweeps_skip_ineligible_issues_and_make_progress(self) -> None:
        missing_fingerprints = self._create_issue(last_state_change_days_ago=10, fingerprints=0, issue_id=UUID(int=1))
        noisy = self._create_issue(last_state_change_days_ago=10, issue_id=UUID(int=2))
        ErrorTrackingIssue.objects.filter(id=noisy.id).update(last_received_at=timezone.now())
        quiet = self._create_issue(last_state_change_days_ago=10, fingerprints=2, issue_id=UUID(int=3))
        later = self._create_issue(last_state_change_days_ago=10, issue_id=UUID(int=4))
        other_team = Team.objects.create(organization=self.organization)
        other_issue = self._create_issue(last_state_change_days_ago=10, issue_id=UUID(int=5))
        ErrorTrackingIssue.objects.filter(id=other_issue.id).update(team_id=other_team.id)
        ErrorTrackingIssueFingerprintV2.objects.filter(issue=other_issue).update(team_id=other_team.id)

        with patch("products.error_tracking.backend.logic.auto_resolve.MAX_ISSUES_PER_TEAM_RUN", 1):
            assert self._run() == 1
            quiet.refresh_from_db()
            later.refresh_from_db()
            assert quiet.status == ErrorTrackingIssue.Status.RESOLVED
            assert later.status == ErrorTrackingIssue.Status.ACTIVE

            self._create_issue(last_state_change_days_ago=10, issue_id=UUID(int=6))
            assert self._run() == 1
            later.refresh_from_db()
            assert later.status == ErrorTrackingIssue.Status.RESOLVED
            assert self._run() == 1
            assert self._run() == 0

            with time_machine.travel(timezone.now() + timedelta(days=4), tick=False):
                assert self._run() == 1
                noisy.refresh_from_db()
                assert noisy.status == ErrorTrackingIssue.Status.RESOLVED
                assert self._run() == 0

        for issue in [missing_fingerprints, other_issue]:
            issue.refresh_from_db()
            assert issue.status == ErrorTrackingIssue.Status.ACTIVE

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

        assert get_auto_resolve_team_ids() == sorted([self.team.id, disabled.id, missing_settings.id])

    @parameterized.expand([("disabled", None), ("increased", 30), ("deleted", None)])
    def test_batch_reloads_settings_after_enumeration(self, name: str, days: int | None) -> None:
        issue = self._create_issue(last_state_change_days_ago=10)
        ErrorTrackingSettings.objects.create(team=self.team, auto_resolve_after_days=3)
        inputs = AutoResolveBatchInputs(team_ids=get_auto_resolve_team_ids())
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

    @parameterized.expand([("recent_receipt", False), ("unknown_receipt", True)])
    @time_machine.travel(timezone.now, tick=False)
    def test_recent_or_unknown_receipt_stays_active(self, _name: str, unknown_receipt: bool) -> None:
        issue = self._create_issue(last_state_change_days_ago=10)
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
            assert self._run() == expected_resolved
            issue.refresh_from_db()
            assert issue.status == (
                ErrorTrackingIssue.Status.RESOLVED if expected_resolved else ErrorTrackingIssue.Status.ACTIVE
            )

    @parameterized.expand([("old", 10, 1), ("new", 0, 0)])
    def test_creation_age_applies_when_state_timestamp_is_missing(
        self, _name: str, created_days_ago: int, expected_resolved: int
    ) -> None:
        issue = self._create_issue(last_state_change_days_ago=10)
        ErrorTrackingIssue.objects.filter(id=issue.id).update(
            created_at=timezone.now() - timedelta(days=created_days_ago), state_updated_at=None
        )
        assert self._run() == expected_resolved

    @parameterized.expand([("merge",), ("split",)])
    def test_regrouping_gives_issues_a_full_inactivity_window(self, operation: str) -> None:
        target = self._create_issue(last_state_change_days_ago=10)
        source = self._create_issue(last_state_change_days_ago=10)
        with self.captureOnCommitCallbacks(execute=True):
            if operation == "merge":
                target.merge([source.id])
            else:
                (target,) = source.split([{"fingerprint": f"fp::{source.id}::0"}])
        ErrorTrackingIssue.objects.filter(id=target.id).update(last_received_at=timezone.now() - timedelta(days=10))
        self._run()
        target.refresh_from_db()
        assert target.status == ErrorTrackingIssue.Status.ACTIVE

    @parameterized.expand([("unchanged", {"status": "active"}), ("renamed", {"name": "New issue name"})])
    def test_manual_update_preserves_concurrent_receipt_and_pending_delivery(
        self, _name: str, fields: dict[str, str]
    ) -> None:
        issue = self._create_issue(last_state_change_days_ago=10)
        received_at = timezone.now()

        def record_receipt(sender: type[ErrorTrackingIssue], instance: ErrorTrackingIssue, **kwargs: object) -> None:
            ErrorTrackingIssue.objects.filter(id=instance.id).update(
                last_received_at=received_at, auto_resolve_sync_requested_at=received_at
            )

        pre_save.connect(record_receipt, sender=ErrorTrackingIssue)
        try:
            update_issue(self.team.id, issue.id, fields=fields, user=self.user, was_impersonated=False)
        finally:
            pre_save.disconnect(record_receipt, sender=ErrorTrackingIssue)

        issue.refresh_from_db()
        assert issue.last_received_at == received_at
        assert issue.auto_resolve_sync_requested_at == received_at
        for field, value in fields.items():
            assert getattr(issue, field) == value

    def test_batch_continues_after_a_team_fails(self) -> None:
        with (
            patch("products.error_tracking.backend.temporal.auto_resolve.activities.close_old_connections"),
            patch("products.error_tracking.backend.temporal.auto_resolve.activities.activity.heartbeat"),
            patch(
                "products.error_tracking.backend.temporal.auto_resolve.activities.auto_resolve_team",
                side_effect=[RuntimeError("database unavailable"), 4],
            ),
        ):
            result = auto_resolve_batch_activity(AutoResolveBatchInputs(team_ids=[1, 2]))

        assert result == AutoResolveBatchResult(teams_processed=1, teams_failed=1, issues_resolved=4)
