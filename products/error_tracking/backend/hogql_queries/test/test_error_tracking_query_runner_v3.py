from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTestKeepIdentities, flush_persons_and_events

from parameterized import parameterized

from products.error_tracking.backend.hogql_queries.test.test_error_tracking_query_runner import (
    ErrorTrackingQueryRunnerTestsMixin,
)
from products.error_tracking.backend.models import ErrorTrackingIssueAssignment, sync_issues_to_clickhouse

from ee.models.rbac.role import Role


class TestErrorTrackingQueryRunnerV3(
    ErrorTrackingQueryRunnerTestsMixin, ClickhouseTestMixin, NonAtomicBaseTestKeepIdentities
):
    __test__ = True
    use_v3 = True

    def setUp(self):
        super().setUp()
        from products.error_tracking.backend.models import ErrorTrackingIssue

        for issue in ErrorTrackingIssue.objects.filter(team=self.team):
            sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.pk)

    def create_events_and_issue(self, *args, **kwargs):
        super().create_events_and_issue(*args, **kwargs)
        issue_id = kwargs.get("issue_id") or args[0]
        sync_issues_to_clickhouse(issue_ids=[issue_id], team_id=self.team.pk)

    def create_issue(self, *args, **kwargs):
        issue = super().create_issue(*args, **kwargs)
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.pk)
        return issue

    @parameterized.expand(
        [
            (
                "default",
                {},
                [
                    "id",
                    "status",
                    "name",
                    "description",
                    "assignee_entity_type",
                    "assignee_entity_id",
                    "last_seen",
                    "first_seen",
                    "function",
                    "source",
                    "library",
                ],
            ),
            (
                "with_aggregations",
                {"withAggregations": True},
                [
                    "id",
                    "status",
                    "name",
                    "description",
                    "assignee_entity_type",
                    "assignee_entity_id",
                    "last_seen",
                    "first_seen",
                    "function",
                    "source",
                    "occurrences",
                    "sessions",
                    "users",
                    "volumeRange",
                    "library",
                ],
            ),
            (
                "with_first_event",
                {"withFirstEvent": True},
                [
                    "id",
                    "status",
                    "name",
                    "description",
                    "assignee_entity_type",
                    "assignee_entity_id",
                    "last_seen",
                    "first_seen",
                    "function",
                    "source",
                    "first_event",
                    "library",
                ],
            ),
        ]
    )
    @freeze_time("2022-01-10T12:11:00")
    def test_column_names(self, _name, kwargs, expected_columns):
        columns = self._calculate(**kwargs)["columns"]
        self.assertEqual(columns, expected_columns)

    @freeze_time("2022-01-10T12:11:00")
    def test_user_assignee(self):
        issue_id = "e9ac529f-ac1c-4a96-bd3a-107034368d64"
        self.create_events_and_issue(
            issue_id=issue_id, fingerprint="assigned_issue_fingerprint", distinct_ids=[self.distinct_id_one]
        )
        flush_persons_and_events()
        ErrorTrackingIssueAssignment.objects.create(issue_id=issue_id, user=self.user, team=self.team)
        # Re-sync after assignment change
        sync_issues_to_clickhouse(issue_ids=[issue_id], team_id=self.team.pk)
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
        # Re-sync after assignment change
        sync_issues_to_clickhouse(issue_ids=[issue_id], team_id=self.team.pk)
        results = self._calculate(assignee={"type": "role", "id": str(role.id)})["results"]
        self.assertEqual([x["id"] for x in results], [issue_id])

    @freeze_time("2022-01-10T12:11:00")
    def test_status(self):
        from products.error_tracking.backend.models import ErrorTrackingIssue

        resolved_issue = ErrorTrackingIssue.objects.get(id=self.issue_id_one)
        resolved_issue.status = ErrorTrackingIssue.Status.RESOLVED
        resolved_issue.save()
        # Re-sync after status change
        sync_issues_to_clickhouse(issue_ids=[self.issue_id_one], team_id=self.team.pk)

        results = self._calculate(status="active")["results"]
        self.assertEqual([r["id"] for r in results], [self.issue_id_three, self.issue_id_two])

        results = self._calculate(status="resolved")["results"]
        self.assertEqual([r["id"] for r in results], [self.issue_id_one])

        results = self._calculate()["results"]
        self.assertEqual([r["id"] for r in results], [self.issue_id_three, self.issue_id_two, self.issue_id_one])

        results = self._calculate(status="all")["results"]
        self.assertEqual([r["id"] for r in results], [self.issue_id_three, self.issue_id_two, self.issue_id_one])
