from datetime import UTC

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client.execute import sync_execute
from posthog.models import Team

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
            SELECT fingerprint, issue_id, issue_name, issue_status, assigned_user_id, assigned_role_id, is_deleted, first_seen, version
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
                "first_seen": r[7],
                "version": r[8],
            }
            for r in rows
        ]

    def _run_backfill(self, *, team_id=None, start_from_team_id=None, end_team_id=None, live_run=True):
        cmd = Command()
        cmd.handle(
            live_run=live_run,
            team_id=team_id,
            start_from_team_id=start_from_team_id,
            end_team_id=end_team_id,
            batch_size=100,
        )

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

    def test_backfill_includes_user_assignment(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="AssignedError", status="active")
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="fp_assigned")
        ErrorTrackingIssueAssignment.objects.create(issue=issue, user=self.user, team=self.team)

        self._run_backfill(team_id=self.team.pk)

        rows = self._get_rows(self.team.pk)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["assigned_user_id"], self.user.pk)

    def test_backfill_includes_role_assignment(self):
        from ee.models import Role

        issue = ErrorTrackingIssue.objects.create(team=self.team, name="AssignedError", status="active")
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="fp_assigned")
        role = Role.objects.create(name="oncall", organization=self.organization)
        ErrorTrackingIssueAssignment.objects.create(issue=issue, role=role, team=self.team)

        self._run_backfill(team_id=self.team.pk)

        rows = self._get_rows(self.team.pk)
        self.assertEqual(len(rows), 1)
        self.assertEqual(str(rows[0]["assigned_role_id"]), str(role.id))

    def test_dry_run_does_not_produce(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="DryRunError", status="active")
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="fp_dry")

        self._run_backfill(team_id=self.team.pk, live_run=False)

        self.assertEqual(self._count_rows(self.team.pk), 0)

    def test_start_from_team_id_skips_earlier_teams(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="SkippedError", status="active")
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="fp_skip")

        # Use a start_from_team_id higher than our team to skip it
        self._run_backfill(start_from_team_id=self.team.pk + 1)

        self.assertEqual(self._count_rows(self.team.pk), 0)

    def test_end_team_id_excludes_later_teams(self):
        team_first = Team.objects.create(organization=self.organization, name="End filter team A")
        team_second = Team.objects.create(organization=self.organization, name="End filter team B")
        self.assertLess(team_first.pk, team_second.pk)

        issue_first = ErrorTrackingIssue.objects.create(team=team_first, name="First", status="active")
        issue_second = ErrorTrackingIssue.objects.create(team=team_second, name="Second", status="active")
        ErrorTrackingIssueFingerprintV2.objects.create(team=team_first, issue=issue_first, fingerprint="fp_first")
        ErrorTrackingIssueFingerprintV2.objects.create(team=team_second, issue=issue_second, fingerprint="fp_second")

        self._run_backfill(end_team_id=team_first.pk)

        self.assertEqual(self._count_rows(team_first.pk), 1)
        self.assertEqual(self._count_rows(team_second.pk), 0)

    def test_start_and_end_team_id_limits_to_range(self):
        team_low = Team.objects.create(organization=self.organization, name="Range low")
        team_mid = Team.objects.create(organization=self.organization, name="Range mid")
        team_high = Team.objects.create(organization=self.organization, name="Range high")
        self.assertLess(team_low.pk, team_mid.pk)
        self.assertLess(team_mid.pk, team_high.pk)

        for team, fp in (
            (team_low, "fp_low"),
            (team_mid, "fp_mid"),
            (team_high, "fp_high"),
        ):
            issue = ErrorTrackingIssue.objects.create(team=team, name="R", status="active")
            ErrorTrackingIssueFingerprintV2.objects.create(team=team, issue=issue, fingerprint=fp)

        self._run_backfill(start_from_team_id=team_mid.pk, end_team_id=team_mid.pk)

        self.assertEqual(self._count_rows(team_low.pk), 0)
        self.assertEqual(self._count_rows(team_mid.pk), 1)
        self.assertEqual(self._count_rows(team_high.pk), 0)

    def test_backfill_version_is_fingerprint_created_at_epoch_ms(self):
        from datetime import datetime

        created_at = datetime(2024, 2, 10, 9, 15, 30, tzinfo=UTC)
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="VersionError", status="active")
        fp = ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="fp_version")
        ErrorTrackingIssueFingerprintV2.objects.filter(pk=fp.pk).update(created_at=created_at)

        self._run_backfill(team_id=self.team.pk)

        rows = self._get_rows(self.team.pk)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["version"], int(created_at.timestamp() * 1000))

    def test_backfill_uses_fingerprint_first_seen(self):
        from datetime import datetime

        first_seen = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="SeenError", status="active")
        fp = ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="fp_seen")
        # auto_now_add ignores passed values, so update after creation
        ErrorTrackingIssueFingerprintV2.objects.filter(pk=fp.pk).update(first_seen=first_seen)

        self._run_backfill(team_id=self.team.pk)

        rows = self._get_rows(self.team.pk)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["first_seen"], first_seen)

    def test_backfill_falls_back_to_issue_created_at_when_first_seen_is_null(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="NullSeenError", status="active")
        fp = ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="fp_null_seen")
        ErrorTrackingIssueFingerprintV2.objects.filter(pk=fp.pk).update(first_seen=None)

        self._run_backfill(team_id=self.team.pk)

        rows = self._get_rows(self.team.pk)
        self.assertEqual(len(rows), 1)
        # CH DateTime64(3) has millisecond precision, so truncate microseconds for comparison
        expected = issue.created_at.replace(microsecond=issue.created_at.microsecond // 1000 * 1000)
        self.assertEqual(rows[0]["first_seen"], expected)

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
