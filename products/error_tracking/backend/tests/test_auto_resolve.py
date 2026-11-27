from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, NonAtomicBaseTest, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.db import connection, transaction

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog

from products.error_tracking.backend.logic import auto_resolve
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingSettings,
    sync_issues_to_clickhouse,
)

NOW = datetime(2026, 10, 20, tzinfo=UTC)
CUTOFF = NOW - timedelta(days=14)


def _create_issue(team, *, created_at: datetime = CUTOFF - timedelta(days=1), **fields) -> ErrorTrackingIssue:
    issue = ErrorTrackingIssue.objects.create(team=team, name="Synthetic error", **fields)
    ErrorTrackingIssue.objects.filter(team=team, pk=issue.pk).update(created_at=created_at)
    ErrorTrackingIssueFingerprintV2.objects.create(team=team, issue=issue, fingerprint=str(issue.pk))
    return issue


class TestAutoResolve(BaseTest):
    @parameterized.expand(
        [
            ("old_receipt", -61, None, -1, "active", False, 1),
            ("receipt_within_cache_grace", -59, None, -1, "active", False, 0),
            ("fresh_receipt", 60, None, -1, "active", False, 0),
            ("new_issue", None, None, 1, "active", False, 0),
            ("recently_changed_issue", None, 1, -1, "active", False, 0),
            ("suppressed_issue", None, None, -1, "suppressed", False, 0),
            ("dry_run", None, None, -1, "active", True, 1),
        ]
    )
    def test_sweep_rechecks_postgres_eligibility(
        self, _name, receipt_minutes, state_minutes, created_minutes, initial_status, dry_run, count
    ):
        ErrorTrackingSettings.objects.create(team=self.team, auto_resolve_after_days=14)
        issue = _create_issue(
            self.team,
            created_at=CUTOFF + timedelta(minutes=created_minutes),
            last_received_at=CUTOFF + timedelta(minutes=receipt_minutes) if receipt_minutes is not None else None,
            state_updated_at=CUTOFF + timedelta(minutes=state_minutes) if state_minutes is not None else None,
            status=initial_status,
        )

        with (
            patch.object(auto_resolve, "team_flag_enabled", return_value=True),
            patch.object(auto_resolve.timezone, "now", return_value=NOW),
            patch.object(auto_resolve, "_issues_seen_since", return_value=set()),
            patch.object(auto_resolve, "sync_issues_to_clickhouse"),
        ):
            assert auto_resolve.auto_resolve_issues(self.team.id, dry_run=dry_run) == count

        issue.refresh_from_db()
        assert issue.status == ("resolved" if count and not dry_run else initial_status)

    def test_sweep_skips_a_window_longer_than_retention(self):
        self.team.event_retention_months = 1
        self.team.save(update_fields=["event_retention_months"])
        ErrorTrackingSettings.objects.create(team=self.team, auto_resolve_after_days=90)
        issue = _create_issue(self.team, created_at=NOW - timedelta(days=180))

        with (
            patch.object(auto_resolve, "team_flag_enabled", return_value=True),
            patch.object(auto_resolve.timezone, "now", return_value=NOW),
        ):
            assert auto_resolve.auto_resolve_issues(self.team.id) == 0
        issue.refresh_from_db()
        assert issue.status == "active"


class TestAutoResolveHistory(ClickhouseTestMixin, BaseTest):
    def test_first_sweep_counts_history_from_before_opt_in(self):
        old = _create_issue(self.team, created_at=NOW - timedelta(days=180))
        active = _create_issue(self.team)
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=active, fingerprint="merged-fingerprint")
        sync_issues_to_clickhouse(issue_ids=[old.pk, active.pk], team_id=self.team.pk)
        for fingerprint, timestamp in (
            (str(old.pk), NOW - timedelta(days=179)),
            ("merged-fingerprint", NOW - timedelta(days=1)),
        ):
            _create_event(
                team=self.team,
                event="$exception",
                distinct_id="user",
                timestamp=timestamp,
                properties={"$exception_fingerprint": fingerprint},
            )
        flush_persons_and_events()
        ErrorTrackingSettings.objects.create(team=self.team, auto_resolve_after_days=14)

        with (
            patch.object(auto_resolve, "team_flag_enabled", return_value=True),
            patch.object(auto_resolve.timezone, "now", return_value=NOW),
        ):
            assert auto_resolve.auto_resolve_issues(self.team.id) == 1
            assert auto_resolve.auto_resolve_issues(self.team.id) == 0

        old.refresh_from_db()
        active.refresh_from_db()
        assert old.status == "resolved"
        assert active.status == "active"
        entry = ActivityLog.objects.get(team_id=self.team.id, item_id=str(old.pk), activity="auto_resolved")
        assert entry.is_system
        assert entry.detail["context"] == {"after_days": 14}


class TestAutoResolveReceiptRace(NonAtomicBaseTest):
    def test_sweep_skips_an_issue_with_an_in_flight_receipt(self):
        ErrorTrackingSettings.objects.create(team=self.team, auto_resolve_after_days=14)
        issue = _create_issue(self.team)
        issues = ErrorTrackingIssue.objects.filter(team=self.team, pk=issue.pk)
        team_id = self.team.id

        def sweep() -> int:
            try:
                return auto_resolve.auto_resolve_issues(team_id)
            finally:
                connection.close()

        with (
            patch.object(auto_resolve, "team_flag_enabled", return_value=True),
            patch.object(auto_resolve.timezone, "now", return_value=NOW),
            patch.object(auto_resolve, "_issues_seen_since", return_value=set()),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            with transaction.atomic():
                issues.update(last_received_at=NOW)
                assert executor.submit(sweep).result(timeout=10) == 0
            assert auto_resolve.auto_resolve_issues(team_id) == 0

        issue.refresh_from_db()
        assert issue.status == "active"
