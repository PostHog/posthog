from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueFingerprintV2

from ee.models.rbac.role import Role


class TestIssueStateSync(ClickhouseTestMixin, APIBaseTest):
    def _create_issue(self, fingerprints=None, **kwargs) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=self.team, **kwargs)
        for fp in fingerprints or []:
            ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fp)
        return issue

    def _get_issue_state_rows(self, team_id=None):
        from posthog.clickhouse.client import sync_execute

        return sync_execute(
            """
            SELECT fingerprint, issue_id, issue_name, issue_status, assigned_user_id, assigned_role_id, issue_severity
            FROM error_tracking_fingerprint_issue_state FINAL
            WHERE team_id = %(team_id)s AND is_deleted = 0
            ORDER BY fingerprint
            """,
            {"team_id": team_id or self.team.pk},
        )

    def setUp(self):
        super().setUp()
        from posthog.clickhouse.client import sync_execute

        from products.error_tracking.backend.sql import TRUNCATE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL

        sync_execute(TRUNCATE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL())

    def test_name_change_syncs(self):
        issue = self._create_issue(fingerprints=["fp_1"], name="Original")
        self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}", data={"name": "Updated"}
        )
        rows = self._get_issue_state_rows()
        assert len(rows) == 1
        assert rows[0][0] == "fp_1"
        assert rows[0][2] == "Updated"

    def test_assign_user_syncs(self):
        issue = self._create_issue(fingerprints=["fp_1"])
        self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}/assign",
            data={"assignee": {"id": self.user.id, "type": "user"}},
        )
        rows = self._get_issue_state_rows()
        assert len(rows) == 1
        assert rows[0][4] == self.user.id  # assigned_user_id

    def test_clear_assignment_syncs(self):
        issue = self._create_issue(fingerprints=["fp_1"])
        self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}/assign",
            data={"assignee": {"id": self.user.id, "type": "user"}},
        )
        rows = self._get_issue_state_rows()
        assert rows[0][4] == self.user.id  # assigned_user_id
        self.client.patch(f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}/assign", data={})
        rows = self._get_issue_state_rows()
        assert len(rows) == 1
        assert rows[0][4] is None  # assigned_user_id cleared
        assert rows[0][5] is None  # assigned_role_id cleared

    def test_assign_role_syncs(self):
        issue = self._create_issue(fingerprints=["fp_1"])
        role = Role.objects.create(name="Eng role", organization=self.organization)
        self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}/assign",
            data={"assignee": {"id": str(role.id), "type": "role"}},
        )
        rows = self._get_issue_state_rows()
        assert len(rows) == 1
        assert str(rows[0][5]) == str(role.id)  # assigned_role_id

    def test_status_change_syncs(self):
        issue = self._create_issue(fingerprints=["fp_1"])
        self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}", data={"status": "resolved"}
        )
        rows = self._get_issue_state_rows()
        assert len(rows) == 1
        assert rows[0][3] == "resolved"  # issue_status

    def test_severity_change_syncs(self):
        issue = self._create_issue(fingerprints=["fp_1"])
        self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}", data={"severity": "high"}
        )
        rows = self._get_issue_state_rows()
        assert len(rows) == 1
        assert rows[0][6] == "high"

    def test_bulk_status_change_syncs(self):
        issue_one = self._create_issue(fingerprints=["fp_one"])
        issue_two = self._create_issue(fingerprints=["fp_two"])
        self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/issues/bulk",
            data={"ids": [str(issue_one.id), str(issue_two.id)], "action": "set_status", "status": "resolved"},
        )
        rows = self._get_issue_state_rows()
        assert len(rows) == 2
        for row in rows:
            assert row[3] == "resolved"  # issue_status

    def test_bulk_assign_syncs(self):
        issue_one = self._create_issue(fingerprints=["fp_one"])
        issue_two = self._create_issue(fingerprints=["fp_two"])
        self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/issues/bulk",
            data={
                "ids": [str(issue_one.id), str(issue_two.id)],
                "action": "assign",
                "assignee": {"id": self.user.id, "type": "user"},
            },
        )
        rows = self._get_issue_state_rows()
        assert len(rows) == 2
        for row in rows:
            assert row[4] == self.user.id  # assigned_user_id

    def test_merge_syncs(self):
        issue_one = self._create_issue(fingerprints=["fp_one"])
        issue_two = self._create_issue(fingerprints=["fp_two"])
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/issues/{issue_one.id}/merge",
                data={"ids": [str(issue_two.id)]},
            )
        rows = self._get_issue_state_rows()
        assert len(rows) == 2
        for row in rows:
            assert str(row[1]) == str(issue_one.id)  # both fingerprints point to issue_one

    def test_split_syncs(self):
        issue = self._create_issue(fingerprints=["fp_keep", "fp_split"])
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}/split",
                data={"fingerprints": [{"fingerprint": "fp_split", "name": "Split issue"}]},
                format="json",
            )
        new_issue_id = response.json()["new_issue_ids"][0]
        rows = self._get_issue_state_rows()
        rows_by_fp = {r[0]: r for r in rows}
        assert str(rows_by_fp["fp_keep"][1]) == str(issue.id)
        assert str(rows_by_fp["fp_split"][1]) == new_issue_id
