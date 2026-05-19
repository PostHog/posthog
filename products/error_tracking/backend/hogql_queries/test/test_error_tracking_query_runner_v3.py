from datetime import UTC, datetime

from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTestKeepIdentities, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    ErrorTrackingIssueFilter,
    ErrorTrackingQuery,
    EventPropertyFilter,
    FilterLogicalOperator,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
)

from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_v3 import ErrorTrackingQueryV3Builder
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

    @parameterized.expand(
        [
            (
                "or_returns_union",
                FilterLogicalOperator.OR_,
                # issue_one (TypeError) and issue_two (ReferenceError) both match
                [True, True, False],
            ),
            (
                "and_returns_intersection",
                FilterLogicalOperator.AND_,
                # No issue has both names — AND yields empty
                [False, False, False],
            ),
        ]
    )
    @freeze_time("2022-01-10T12:11:00")
    def test_filter_group_operator(self, _name, operator: FilterLogicalOperator, expected_membership: list[bool]):
        results = self._calculate(
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=operator,
                        values=[
                            ErrorTrackingIssueFilter(
                                key="name", value=[self.issue_name_one], operator=PropertyOperator.EXACT
                            ),
                            ErrorTrackingIssueFilter(
                                key="name", value=[self.issue_name_two], operator=PropertyOperator.EXACT
                            ),
                        ],
                    )
                ],
            )
        )["results"]
        result_ids = {r["id"] for r in results}
        expected_ids = {
            issue_id
            for issue_id, included in zip(
                [self.issue_id_one, self.issue_id_two, self.issue_id_three], expected_membership
            )
            if included
        }
        self.assertEqual(result_ids, expected_ids)

    @freeze_time("2022-01-10T12:11:00")
    def test_nested_filter_group_routes_issue_filters_to_issue_fields(self):
        filter_group = PropertyGroupFilter(
            type=FilterLogicalOperator.AND_,
            values=[
                PropertyGroupFilterValue(
                    type=FilterLogicalOperator.AND_,
                    values=[
                        PropertyGroupFilterValue(
                            type=FilterLogicalOperator.OR_,
                            values=[
                                EventPropertyFilter(key="$browser", value=["Firefox"], operator=PropertyOperator.EXACT),
                                EventPropertyFilter(key="$browser", value=["Chrome"], operator=PropertyOperator.EXACT),
                                ErrorTrackingIssueFilter(
                                    key="name", value=[self.issue_name_one], operator=PropertyOperator.EXACT
                                ),
                            ],
                        ),
                        EventPropertyFilter(
                            key="$exception_issue_id", value=[self.issue_id_one], operator=PropertyOperator.EXACT
                        ),
                    ],
                )
            ],
        )

        builder = ErrorTrackingQueryV3Builder(
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                dateRange=DateRange(date_from="-7d"),
                filterGroup=filter_group,
                orderBy="last_seen",
                volumeResolution=1,
                useQueryV3=True,
            ),
            team=self.team,
            date_from=datetime(2022, 1, 3, tzinfo=UTC),
            date_to=datetime(2022, 1, 10, tzinfo=UTC),
        )
        user_filter_expr = builder._user_filter_expr()
        assert user_filter_expr is not None
        user_filter_hogql = user_filter_expr.to_hogql()
        self.assertIn("e.issue_name", user_filter_hogql)
        self.assertNotIn("properties.name", user_filter_hogql)

        results = self._calculate(filterGroup=filter_group)["results"]
        self.assertEqual([r["id"] for r in results], [self.issue_id_one])

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
