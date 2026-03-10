from freezegun import freeze_time
from posthog.test.base import (
    ClickhouseTestMixin,
    NonAtomicBaseTest,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from django.db import connections

from products.error_tracking.backend.hogql_queries.test.test_error_tracking_query_runner import (
    ErrorTrackingQueryRunnerTestsMixin,
)
from products.error_tracking.backend.models import ErrorTrackingIssueAssignment

from ee.models.rbac.role import Role


class TestErrorTrackingQueryRunnerV2(ErrorTrackingQueryRunnerTestsMixin, ClickhouseTestMixin, NonAtomicBaseTest):
    __test__ = True
    use_v2 = True

    # we have to do this manually there because standard django test class runs in a django transaction hence data is invisibile to CH via PH connector.
    # I had to change the base test class to NonAtomicBaseTest to allow this. And that's why I have to tear down the data manually.
    def _fixture_teardown(self):
        current_team_id = getattr(self.team, "id", None) if hasattr(self, "team") else None

        with connections["default"].cursor() as cursor:
            cursor.execute("""
                TRUNCATE
                    posthog_errortrackingissueassignment,
                    posthog_errortrackingissuefingerprintv2,
                    posthog_errortrackingissue,
                    posthog_organizationmembership,
                    posthog_user,
                    posthog_team,
                    posthog_project,
                    posthog_organization
                CASCADE
            """)

        if current_team_id:
            with connections["persons_db_writer"].cursor() as cursor:
                cursor.execute(f"DELETE FROM posthog_persondistinctid WHERE team_id = {current_team_id}")
                cursor.execute(f"DELETE FROM posthog_person WHERE team_id = {current_team_id}")

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_column_names(self):
        columns = self._calculate()["columns"]
        self.assertEqual(
            columns,
            [
                "id",
                "status",
                "name",
                "description",
                "last_seen",
                "first_seen",
                "assignee_user_id",
                "assignee_role_id",
                "function",
                "source",
                "library",
            ],
        )

        columns = self._calculate(withAggregations=True)["columns"]
        self.assertEqual(
            columns,
            [
                "id",
                "status",
                "name",
                "description",
                "last_seen",
                "first_seen",
                "assignee_user_id",
                "assignee_role_id",
                "function",
                "source",
                "occurrences",
                "sessions",
                "users",
                "volumeRange",
                "library",
            ],
        )

        columns = self._calculate(withFirstEvent=True)["columns"]
        self.assertEqual(
            columns,
            [
                "id",
                "status",
                "name",
                "description",
                "last_seen",
                "first_seen",
                "assignee_user_id",
                "assignee_role_id",
                "function",
                "source",
                "first_event",
                "library",
            ],
        )

    @freeze_time("2022-01-10T12:11:00")
    def test_user_assignee(self):
        issue_id = "e9ac529f-ac1c-4a96-bd3a-107034368d64"
        self.create_events_and_issue(
            issue_id=issue_id, fingerprint="assigned_issue_fingerprint", distinct_ids=[self.distinct_id_one]
        )
        flush_persons_and_events()
        ErrorTrackingIssueAssignment.objects.create(issue_id=issue_id, user=self.user, team=self.team)
        results = self._calculate(assignee={"type": "user", "id": self.user.pk})["results"]
        self.assertEqual([x["id"] for x in results], [issue_id])

    @freeze_time("2022-01-10T12:11:00")
    def test_role_assignee(self):
        issue_id = "e9ac529f-ac1c-4a96-bd3a-107034368d64"
        self.create_events_and_issue(
            issue_id=issue_id, fingerprint="assigned_issue_fingerprint", distinct_ids=[self.distinct_id_one]
        )
        flush_persons_and_events()
        role = Role.objects.create(name="Test Team", organization=self.organization)
        ErrorTrackingIssueAssignment.objects.create(issue_id=issue_id, role=role, team=self.team)
        results = self._calculate(assignee={"type": "role", "id": str(role.id)})["results"]
        self.assertEqual([x["id"] for x in results], [issue_id])
