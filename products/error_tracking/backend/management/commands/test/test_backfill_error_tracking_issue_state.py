from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client.execute import sync_execute

from products.error_tracking.backend.management.commands.backfill_error_tracking_issue_state import Command
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
)


class TestBackfillErrorTrackingIssueState(ClickhouseTestMixin, BaseTest):
    def _count_rows(self, team_id: int) -> int:
        [(count,)] = sync_execute(
            "SELECT count() FROM error_tracking_fingerprint_issue_state WHERE team_id = %(team_id)s",
            {"team_id": team_id},
        )
        return count

    def _get_rows(self, team_id: int) -> list[dict]:
        rows = sync_execute(
            """
            SELECT fingerprint, issue_id, issue_name, issue_status, assigned_user_id, assigned_role_id, is_deleted
            FROM error_tracking_fingerprint_issue_state
            WHERE team_id = %(team_id)s
            ORDER BY fingerprint
            """,
            {"team_id": team_id},
        )
        return [
            {
                "fingerprint": r[0],
                "issue_id": str(r[1]),
                "issue_name": r[2],
                "issue_status": r[3],
                "assigned_user_id": r[4],
                "assigned_role_id": r[5],
                "is_deleted": r[6],
            }
            for r in rows
        ]

    def _run_backfill(self, *, team_id=None, start_from_team_id=None, live_run=True):
        cmd = Command()
        cmd.handle(live_run=live_run, team_id=team_id, start_from_team_id=start_from_team_id, batch_size=100)

    def test_backfill_creates_rows_in_clickhouse(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="TestError", status="active")
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="fp_one")
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="fp_two")

        self.assertEqual(self._count_rows(self.team.pk), 0)

        self._run_backfill(team_id=self.team.pk)

        rows = self._get_rows(self.team.pk)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["fingerprint"], "fp_one")
        self.assertEqual(rows[0]["issue_id"], str(issue.id))
        self.assertEqual(rows[0]["issue_name"], "TestError")
        self.assertEqual(rows[0]["issue_status"], "active")
        self.assertEqual(rows[1]["fingerprint"], "fp_two")

    def test_backfill_includes_assignment(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="AssignedError", status="active")
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="fp_assigned")
        ErrorTrackingIssueAssignment.objects.create(issue=issue, user=self.user, team=self.team)

        self._run_backfill(team_id=self.team.pk)

        rows = self._get_rows(self.team.pk)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["assigned_user_id"], self.user.pk)

    def test_dry_run_does_not_produce(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="DryRunError", status="active")
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="fp_dry")

        cmd = Command()
        cmd.handle(live_run=False, team_id=self.team.pk, start_from_team_id=None, batch_size=100)

        self.assertEqual(self._count_rows(self.team.pk), 0)

    def test_start_from_team_id_skips_earlier_teams(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="SkippedError", status="active")
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="fp_skip")

        # Use a start_from_team_id higher than our team to skip it
        self._run_backfill(start_from_team_id=self.team.pk + 1)

        self.assertEqual(self._count_rows(self.team.pk), 0)

    def test_backfill_multiple_issues(self):
        issue_a = ErrorTrackingIssue.objects.create(team=self.team, name="ErrorA", status="active")
        issue_b = ErrorTrackingIssue.objects.create(team=self.team, name="ErrorB", status="resolved")
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue_a, fingerprint="fp_a")
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue_b, fingerprint="fp_b")

        self._run_backfill(team_id=self.team.pk)

        rows = self._get_rows(self.team.pk)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["issue_status"], "active")
        self.assertEqual(rows[1]["issue_status"], "resolved")
