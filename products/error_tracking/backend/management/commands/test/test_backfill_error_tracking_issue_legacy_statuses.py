from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client.execute import sync_execute
from posthog.models import Organization, Team

from products.error_tracking.backend.management.commands.backfill_error_tracking_issue_legacy_statuses import Command
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueFingerprintV2


class TestBackfillErrorTrackingIssueLegacyStatuses(ClickhouseTestMixin, BaseTest):
    def _run(
        self,
        *,
        live_run: bool = True,
        team_id: int | None = None,
        start_from_team_id: int | None = None,
        end_team_id: int | None = None,
        status: str | None = None,
    ) -> None:
        Command().handle(
            live_run=live_run,
            team_id=team_id,
            start_from_team_id=start_from_team_id,
            end_team_id=end_team_id,
            status=status,
        )

    def _make_issue(self, *, team: Team, status: str, fingerprint: str | None = None) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=team, status=status)
        if fingerprint is not None:
            ErrorTrackingIssueFingerprintV2.objects.create(team=team, issue=issue, fingerprint=fingerprint)
        return issue

    def _ch_status_for(self, *, team_id: int, fingerprint: str) -> str | None:
        rows = sync_execute(
            """
            SELECT issue_status
            FROM error_tracking_fingerprint_issue_state FINAL
            WHERE team_id = %(team_id)s AND fingerprint = %(fingerprint)s
            """,
            {"team_id": team_id, "fingerprint": fingerprint},
        )
        return rows[0][0] if rows else None

    def test_dry_run_does_not_modify_rows(self):
        archived = self._make_issue(team=self.team, status=ErrorTrackingIssue.Status.ARCHIVED, fingerprint="fp_a")
        pending = self._make_issue(team=self.team, status=ErrorTrackingIssue.Status.PENDING_RELEASE, fingerprint="fp_p")

        self._run(live_run=False)

        archived.refresh_from_db()
        pending.refresh_from_db()
        assert archived.status == ErrorTrackingIssue.Status.ARCHIVED
        assert pending.status == ErrorTrackingIssue.Status.PENDING_RELEASE

    def test_live_run_resolves_legacy_statuses_and_syncs_to_clickhouse(self):
        archived = self._make_issue(team=self.team, status=ErrorTrackingIssue.Status.ARCHIVED, fingerprint="fp_a")
        pending = self._make_issue(team=self.team, status=ErrorTrackingIssue.Status.PENDING_RELEASE, fingerprint="fp_p")
        active_unchanged = self._make_issue(
            team=self.team, status=ErrorTrackingIssue.Status.ACTIVE, fingerprint="fp_active"
        )

        self._run(live_run=True)

        archived.refresh_from_db()
        pending.refresh_from_db()
        active_unchanged.refresh_from_db()
        assert archived.status == ErrorTrackingIssue.Status.RESOLVED
        assert pending.status == ErrorTrackingIssue.Status.RESOLVED
        assert active_unchanged.status == ErrorTrackingIssue.Status.ACTIVE

        assert self._ch_status_for(team_id=self.team.pk, fingerprint="fp_a") == "resolved"
        assert self._ch_status_for(team_id=self.team.pk, fingerprint="fp_p") == "resolved"
        # The active issue was not touched, so no CH row was produced for it by the backfill.
        assert self._ch_status_for(team_id=self.team.pk, fingerprint="fp_active") is None

    def test_status_filter_limits_scope(self):
        archived = self._make_issue(team=self.team, status=ErrorTrackingIssue.Status.ARCHIVED, fingerprint="fp_a")
        pending = self._make_issue(team=self.team, status=ErrorTrackingIssue.Status.PENDING_RELEASE, fingerprint="fp_p")

        self._run(live_run=True, status=ErrorTrackingIssue.Status.ARCHIVED)

        archived.refresh_from_db()
        pending.refresh_from_db()
        assert archived.status == ErrorTrackingIssue.Status.RESOLVED
        assert pending.status == ErrorTrackingIssue.Status.PENDING_RELEASE

    def test_team_id_filter_isolates_other_teams(self):
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other team")

        own = self._make_issue(team=self.team, status=ErrorTrackingIssue.Status.ARCHIVED)
        other = self._make_issue(team=other_team, status=ErrorTrackingIssue.Status.ARCHIVED)

        self._run(live_run=True, team_id=self.team.pk)

        own.refresh_from_db()
        other.refresh_from_db()
        assert own.status == ErrorTrackingIssue.Status.RESOLVED
        assert other.status == ErrorTrackingIssue.Status.ARCHIVED

    def test_idempotent_on_clean_dataset(self):
        # Re-running on a dataset with no legacy statuses should be a no-op.
        self._make_issue(team=self.team, status=ErrorTrackingIssue.Status.ACTIVE)
        self._run(live_run=True)  # should not raise, should not change anything

        counts = ErrorTrackingIssue.objects.filter(team=self.team).values_list("status", flat=True)
        assert all(c == ErrorTrackingIssue.Status.ACTIVE for c in counts)
