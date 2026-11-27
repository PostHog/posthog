from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, NonAtomicBaseTest
from unittest.mock import patch

from django.db import connection, transaction

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog

from products.error_tracking.backend.logic import auto_resolve
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingSettings,
)

NOW = datetime(2026, 10, 20, tzinfo=UTC)
CUTOFF = NOW - timedelta(days=14)


class TestAutoResolve(BaseTest):
    def _issue(self, *, created_at: datetime = CUTOFF - timedelta(days=1), **fields) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="Synthetic error", **fields)
        ErrorTrackingIssue.objects.filter(team=self.team, pk=issue.pk).update(created_at=created_at)
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=str(issue.pk))
        return issue

    @parameterized.expand(
        [
            ("no_receipts_after_enablement", -1, None, None, -1, "active", False, 1),
            ("old_receipt", -1, -61, None, -1, "active", False, 1),
            ("receipt_within_cache_grace", -1, -59, None, -1, "active", False, 0),
            ("fresh_receipt", -1, 60, None, -1, "active", False, 0),
            ("observation_still_warming_up", 0, None, None, -1, "active", False, 0),
            ("new_issue", -1, None, None, 1, "active", False, 0),
            ("recently_changed_issue", -1, None, 1, -1, "active", False, 0),
            ("suppressed_issue", -1, None, None, -1, "suppressed", False, 0),
            ("dry_run", -1, None, None, -1, "active", True, 1),
        ]
    )
    def test_sweep_only_resolves_observed_quiet_issues(
        self,
        _name,
        observation_minutes,
        receipt_minutes,
        state_minutes,
        created_minutes,
        initial_status,
        dry_run,
        count,
    ):
        ErrorTrackingSettings.objects.create(
            team=self.team,
            auto_resolve_after_days=14,
            auto_resolve_observation_started_at=CUTOFF + timedelta(minutes=observation_minutes),
        )
        issue = self._issue(
            created_at=CUTOFF + timedelta(minutes=created_minutes),
            last_received_at=CUTOFF + timedelta(minutes=receipt_minutes) if receipt_minutes is not None else None,
            state_updated_at=CUTOFF + timedelta(minutes=state_minutes) if state_minutes is not None else None,
            status=initial_status,
        )

        with (
            patch.object(auto_resolve, "team_flag_enabled", return_value=True),
            patch.object(auto_resolve.timezone, "now", return_value=NOW),
        ):
            assert auto_resolve.auto_resolve_issues(self.team.id, dry_run=dry_run) == count
            if count and not dry_run:
                assert auto_resolve.auto_resolve_issues(self.team.id) == 0

        issue.refresh_from_db()
        if count and not dry_run:
            assert issue.status == "resolved"
            assert issue.auto_resolve_sync_requested_at == NOW
            entry = ActivityLog.objects.get(team_id=self.team.id, item_id=str(issue.pk), activity="auto_resolved")
            assert entry.is_system
            assert entry.detail["context"] == {"after_days": 14}
        else:
            assert issue.status == initial_status
            assert issue.auto_resolve_sync_requested_at is None

    def test_projection_does_not_clear_an_unacknowledged_or_newer_request(self):
        issue = self._issue(status="resolved", auto_resolve_sync_requested_at=CUTOFF)
        with patch.object(auto_resolve, "sync_issues_to_clickhouse", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                auto_resolve.sync_pending_auto_resolve_issues(self.team.id)
        issue.refresh_from_db()
        assert issue.auto_resolve_sync_requested_at == CUTOFF

        def reopen_during_delivery(**kwargs):
            ErrorTrackingIssue.objects.filter(team=self.team, pk=issue.pk).update(
                status="active", auto_resolve_sync_requested_at=NOW
            )

        with patch.object(auto_resolve, "sync_issues_to_clickhouse", side_effect=reopen_during_delivery):
            assert auto_resolve.sync_pending_auto_resolve_issues(self.team.id) == 0
        issue.refresh_from_db()
        assert issue.auto_resolve_sync_requested_at == NOW

        with patch.object(auto_resolve, "sync_issues_to_clickhouse") as sync:
            assert auto_resolve.sync_pending_auto_resolve_issues(self.team.id) == 1
            sync.assert_called_once_with(issue_ids=[issue.pk], team_id=self.team.id, wait_for_delivery=True)
        issue.refresh_from_db()
        assert issue.auto_resolve_sync_requested_at is None


class TestAutoResolveReceiptRace(NonAtomicBaseTest):
    def test_sweep_skips_an_issue_with_an_in_flight_receipt(self):
        ErrorTrackingSettings.objects.create(
            team=self.team,
            auto_resolve_after_days=14,
            auto_resolve_observation_started_at=CUTOFF - timedelta(days=1),
        )
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="race")
        issues = ErrorTrackingIssue.objects.filter(team=self.team, pk=issue.pk)
        issues.update(created_at=CUTOFF - timedelta(days=1))
        team_id = self.team.id

        def sweep() -> int:
            try:
                return auto_resolve.auto_resolve_issues(team_id)
            finally:
                connection.close()

        with (
            patch.object(auto_resolve, "team_flag_enabled", return_value=True),
            patch.object(auto_resolve.timezone, "now", return_value=NOW),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            with transaction.atomic():
                issues.update(last_received_at=NOW)
                assert executor.submit(sweep).result(timeout=10) == 0
            assert auto_resolve.auto_resolve_issues(team_id) == 0

        issue.refresh_from_db()
        assert issue.status == "active"
