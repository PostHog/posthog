from freezegun import freeze_time
from posthog.test.base import (
    ClickhouseTestMixin,
    NonAtomicBaseTestKeepIdentities,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from products.error_tracking.backend.hogql_queries.test.test_error_tracking_query_runner import (
    ErrorTrackingQueryRunnerTestsMixin,
)
from products.error_tracking.backend.models import ErrorTrackingIssueAssignment

from ee.models.rbac.role import Role


class TestErrorTrackingQueryRunnerV2(
    ErrorTrackingQueryRunnerTestsMixin, ClickhouseTestMixin, NonAtomicBaseTestKeepIdentities
):
    __test__ = True
    use_v2 = True

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
