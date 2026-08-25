from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import (
    ClickhouseTestMixin,
    NonAtomicBaseTestKeepIdentities,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest import TestCase, mock

from django.db import OperationalError
from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    DateRange,
    ErrorTrackingIssueFilter,
    ErrorTrackingQuery,
    EventPropertyFilter,
    FilterLogicalOperator,
    PersonPropertyFilter,
    PersonsOnEventsMode,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.utils import uuid7
from posthog.rbac.user_access_control import UserAccessControlError

from products.error_tracking.backend.hogql_queries.access import ErrorTrackingQueryRunnerAccessMixin
from products.error_tracking.backend.hogql_queries.error_tracking_breakdowns_query_runner import (
    ErrorTrackingBreakdownsQueryRunner,
)
from products.error_tracking.backend.hogql_queries.error_tracking_fingerprint_projection_query_runner import (
    ErrorTrackingFingerprintProjectionQueryRunner,
)
from products.error_tracking.backend.hogql_queries.error_tracking_issue_correlation_query_runner import (
    ErrorTrackingIssueCorrelationQueryRunner,
)
from products.error_tracking.backend.hogql_queries.error_tracking_query_builder import ErrorTrackingQueryBuilder
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_utils import search_tokenizer
from products.error_tracking.backend.hogql_queries.error_tracking_similar_issues_query_runner import (
    ErrorTrackingSimilarIssuesQueryRunner,
)
from products.error_tracking.backend.hogql_queries.issue_state_overlay import (
    MAX_RECENT_ISSUE_STATES,
    load_recent_issue_states,
)
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    override_error_tracking_issue_fingerprint,
    sync_issues_to_clickhouse,
    update_error_tracking_issue_fingerprints,
)

from ee.models.rbac.access_control import AccessControl
from ee.models.rbac.role import Role


class TestErrorTrackingQueryRunner(ClickhouseTestMixin, NonAtomicBaseTestKeepIdentities):
    distinct_id_one = "user_1"
    distinct_id_two = "user_2"

    group0_id = "lolol0:xxx"
    group1_id = "lolol1:xxx"

    issue_name_one = "TypeError"
    issue_name_two = "ReferenceError"
    issue_id_one = "01936e7f-d7ff-7314-b2d4-7627981e34f0"
    issue_id_two = "01936e80-5e69-7e70-b837-871f5cdad28b"
    issue_id_three = "01936e80-aa51-746f-aec4-cdf16a5c5332"
    issue_one_fingerprint = "issue_one_fingerprint"
    issue_two_fingerprint = "issue_two_fingerprint"
    issue_three_fingerprint = "issue_three_fingerprint"

    def override_fingerprint(self, fingerprint, issue_id, version=1):
        update_error_tracking_issue_fingerprints(team_id=self.team.pk, issue_id=issue_id, fingerprints=[fingerprint])
        override_error_tracking_issue_fingerprint(
            team_id=self.team.pk, fingerprint=fingerprint, issue_id=issue_id, version=version
        )
        # reflect the new fingerprint -> issue mapping in the denormalized ClickHouse table
        sync_issues_to_clickhouse(issue_ids=[issue_id], team_id=self.team.pk)

    def create_issue(self, issue_id, fingerprint, name=None, status=ErrorTrackingIssue.Status.ACTIVE):
        issue = ErrorTrackingIssue.objects.create(id=issue_id, team=self.team, status=status, name=name)
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.pk)
        return issue

    def create_events_and_issue(
        self,
        issue_id,
        fingerprint,
        distinct_ids,
        timestamp=None,
        exception_list=None,
        additional_properties=None,
        issue_name=None,
        person_id=None,
    ):
        if timestamp:
            with freeze_time(timestamp):
                self.create_issue(issue_id, fingerprint, name=issue_name)
        else:
            self.create_issue(issue_id, fingerprint, name=issue_name)

        event_properties = {"$exception_issue_id": issue_id, "$exception_fingerprint": fingerprint}
        if exception_list:
            event_properties["$exception_list"] = exception_list

        for distinct_id in distinct_ids:
            _create_event(
                distinct_id=distinct_id,
                event="$exception",
                team=self.team,
                properties={**event_properties, **additional_properties} if additional_properties else event_properties,
                timestamp=timestamp,
                person_id=person_id,
            )

        sync_issues_to_clickhouse(issue_ids=[issue_id], team_id=self.team.pk)

    @classmethod
    def setUpClass(cls) -> None:
        from ee.clickhouse.materialized_columns.columns import get_materialized_columns, materialize

        materialized_columns = get_materialized_columns("events")
        for property_name in ("$exception_issue_id", "$exception_types", "$exception_values"):
            if (property_name, "properties") not in materialized_columns:
                materialize("events", property_name, is_nullable=property_name == "$exception_issue_id")
        super().setUpClass()

    def test_fingerprint_grouping_key_uses_stable_json_expression(self):
        response = self._calculate()

        self.assertIn("JSONExtractString(e.properties, '$exception_fingerprint')", response["hogql"])
        self.assertNotIn("mat_$exception_fingerprint", response["hogql"])

    @parameterized.expand(
        [
            (PersonsOnEventsMode.DISABLED,),
            (PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,),
            (PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,),
            (PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,),
        ]
    )
    def test_user_aggregation_does_not_resolve_person_overrides(self, persons_on_events_mode):
        self.team.modifiers = {"personsOnEventsMode": persons_on_events_mode}

        response = self._calculate(withAggregations=True)

        self.assertIn("e.event_person_id", response["hogql"])
        self.assertNotIn("person_distinct_id_overrides", response["hogql"])

    def setUp(self):
        super().setUp()

        with freeze_time("2020-01-10 12:11:00"):
            _create_person(
                team=self.team,
                distinct_ids=[self.distinct_id_one],
                is_identified=True,
            )
            _create_person(
                team=self.team,
                properties={
                    "email": "email@posthog.com",
                    "name": "Test User",
                },
                distinct_ids=[self.distinct_id_two],
                is_identified=True,
            )

            self.create_events_and_issue(
                issue_id=self.issue_id_one,
                issue_name=self.issue_name_one,
                fingerprint=self.issue_one_fingerprint,
                distinct_ids=[self.distinct_id_one, self.distinct_id_two],
                timestamp=now() - relativedelta(hours=3),
            )
            self.create_events_and_issue(
                issue_id=self.issue_id_two,
                issue_name=self.issue_name_two,
                fingerprint=self.issue_two_fingerprint,
                distinct_ids=[self.distinct_id_one],
                timestamp=now() - relativedelta(hours=2),
            )
            self.create_events_and_issue(
                issue_id=self.issue_id_three,
                fingerprint=self.issue_three_fingerprint,
                distinct_ids=[self.distinct_id_two],
                timestamp=now() - relativedelta(hours=1),
            )

        flush_persons_and_events()
        # test fixtures write each person row twice at the same version; collapse them so the
        # person join (test-account filter, person-property search) doesn't fan out count()
        sync_execute("OPTIMIZE TABLE person FINAL")

    def _calculate(
        self,
        dateRange=None,
        assignee=None,
        issueId=None,
        filterTestAccounts=False,
        searchQuery=None,
        filterGroup=None,
        orderBy="last_seen",
        status=None,
        volumeResolution=1,
        withAggregations=False,
        withFirstEvent=False,
        personId=None,
        groupKey=None,
        groupTypeIndex=None,
    ):
        return (
            ErrorTrackingQueryRunner(
                team=self.team,
                query=ErrorTrackingQuery(
                    kind="ErrorTrackingQuery",
                    # Fixtures span back to 2020; request all-time so these correctness tests
                    # see them regardless of the production default window (covered by the
                    # parse_relative_date_from unit tests below).
                    dateRange=DateRange(date_from="all") if dateRange is None else dateRange,
                    assignee=assignee,
                    issueId=issueId,
                    filterTestAccounts=filterTestAccounts,
                    searchQuery=searchQuery,
                    filterGroup=filterGroup,
                    orderBy=orderBy,  # pyright: ignore[reportArgumentType]
                    status=status,
                    volumeResolution=volumeResolution,
                    withFirstEvent=withFirstEvent,
                    withAggregations=withAggregations,
                    personId=personId,
                    groupKey=groupKey,
                    groupTypeIndex=groupTypeIndex,
                ),
            )
            .calculate()
            .model_dump()
        )

    @parameterized.expand(
        [
            (
                "default",
                {},
                [
                    "id",
                    "status",
                    "severity",
                    "name",
                    "description",
                    "assignee_user_id",
                    "assignee_role_id",
                    "first_seen",
                    "last_seen",
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
                    "severity",
                    "name",
                    "description",
                    "assignee_user_id",
                    "assignee_role_id",
                    "first_seen",
                    "last_seen",
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
                    "severity",
                    "name",
                    "description",
                    "assignee_user_id",
                    "assignee_role_id",
                    "first_seen",
                    "last_seen",
                    "function",
                    "source",
                    "first_event",
                    "library",
                ],
            ),
            (
                "with_aggregations_and_first_event",
                {"withAggregations": True, "withFirstEvent": True},
                [
                    "id",
                    "status",
                    "severity",
                    "name",
                    "description",
                    "assignee_user_id",
                    "assignee_role_id",
                    "first_seen",
                    "last_seen",
                    "function",
                    "source",
                    "occurrences",
                    "sessions",
                    "users",
                    "volumeRange",
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
    def test_date_range_resolution(self):
        date_from = ErrorTrackingQueryRunner.parse_relative_date_from("-1d")
        date_to = ErrorTrackingQueryRunner.parse_relative_date_to("+1d")
        self.assertEqual(date_from, datetime(2022, 1, 9, 12, 11, 0, tzinfo=ZoneInfo(key="UTC")))
        self.assertEqual(date_to, datetime(2022, 1, 11, 12, 11, 0, tzinfo=ZoneInfo(key="UTC")))

    def test_event_fetching_defaults_off(self):
        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                dateRange=DateRange(),
                orderBy="last_seen",  # pyright: ignore[reportArgumentType]
                volumeResolution=1,
            ),
        )
        self.assertFalse(runner.query.withFirstEvent)
        self.assertFalse(runner.query.withLastEvent)
        self.assertTrue(runner.query.withAggregations)

    @freeze_time("2022-01-10T12:11:00")
    def test_cache_payload_keeps_latest_issue_state_watermark_after_overlay_expiry(self):
        query = ErrorTrackingQuery(
            kind="ErrorTrackingQuery",
            dateRange=DateRange(date_from="all"),
            orderBy="last_seen",  # pyright: ignore[reportArgumentType]
            volumeResolution=1,
        )
        initial_payload = ErrorTrackingQueryRunner(
            team=self.team, query=query.model_copy(deep=True)
        ).get_cache_payload()
        mutation_timestamp = now() - timedelta(seconds=61)
        ErrorTrackingIssue.objects.filter(id=self.issue_id_one).update(state_updated_at=mutation_timestamp)

        mutated_payload = ErrorTrackingQueryRunner(
            team=self.team, query=query.model_copy(deep=True)
        ).get_cache_payload()
        with freeze_time("2022-01-10T12:13:00"):
            expired_payload = ErrorTrackingQueryRunner(
                team=self.team, query=query.model_copy(deep=True)
            ).get_cache_payload()

        self.assertNotEqual(
            initial_payload["error_tracking_issue_state_watermark"],
            mutated_payload["error_tracking_issue_state_watermark"],
        )
        self.assertEqual(
            mutated_payload["error_tracking_issue_state_watermark"],
            expired_payload["error_tracking_issue_state_watermark"],
        )

    def test_cache_payload_degrades_when_watermark_read_fails(self):
        query = ErrorTrackingQuery(
            kind="ErrorTrackingQuery",
            dateRange=DateRange(date_from="all"),
            orderBy="last_seen",  # pyright: ignore[reportArgumentType]
            volumeResolution=1,
        )
        with mock.patch(
            "products.error_tracking.backend.hogql_queries.error_tracking_query_runner.latest_issue_state_watermark",
            side_effect=OperationalError("query_wait_timeout"),
        ):
            payload = ErrorTrackingQueryRunner(team=self.team, query=query).get_cache_payload()

        self.assertEqual(payload["error_tracking_issue_state_watermark"], "unavailable")

    @freeze_time("2022-01-10T12:11:00")
    def test_missing_date_from_defaults_to_seven_days(self):
        # A missing date_from must default to a bounded 7-day window, not all-time.
        date_from = ErrorTrackingQueryRunner.parse_relative_date_from(None)
        self.assertEqual(date_from, datetime(2022, 1, 3, 12, 11, 0, tzinfo=ZoneInfo(key="UTC")))

    @freeze_time("2022-01-10T12:11:00")
    def test_date_to_only_window_ends_at_date_to(self):
        # date_to-only queries must anchor the default window to date_to, not to now.
        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                dateRange=DateRange(date_to="2021-06-01"),
                orderBy="last_seen",  # pyright: ignore[reportArgumentType]
                volumeResolution=1,
            ),
        )
        self.assertEqual(runner.date_from, runner.date_to - timedelta(days=7))

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_issue_grouping(self):
        results = self._calculate(issueId=self.issue_id_one, withAggregations=True)["results"]
        # returns a single group with multiple errors
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.issue_id_one)
        self.assertEqual(results[0]["aggregations"]["occurrences"], 2)

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_search_query(self):
        self.create_events_and_issue(
            issue_id="01936e81-b0ce-7b56-8497-791e505b0d0c",
            fingerprint="fingerprint_DatabaseNotFoundX",
            distinct_ids=[self.distinct_id_one],
            exception_list=[{"type": "DatabaseNotFoundX", "value": "this is the same error message"}],
            additional_properties={"$exception_types": "['DatabaseNotFoundX']"},
        )
        self.create_events_and_issue(
            issue_id="01936e81-f5ce-79b1-99f1-f0e9675fcfef",
            fingerprint="fingerprint_DatabaseNotFoundY",
            distinct_ids=[self.distinct_id_one],
            exception_list=[{"type": "DatabaseNotFoundY", "value": "this is the same error message"}],
            additional_properties={"$exception_types": "['DatabaseNotFoundY']"},
        )
        self.create_events_and_issue(
            issue_id="01936e82-241e-7e27-b47d-6659c54eb0be",
            fingerprint="fingerprint_xyz",
            distinct_ids=[self.distinct_id_two],
            exception_list=[{"type": "xyz", "value": "this is the same error message"}],
            additional_properties={"$exception_types": "['xyz']"},
        )
        flush_persons_and_events()

        results = sorted(
            self._calculate(
                dateRange=DateRange(date_from="-1d", date_to="+1d"),
                filterTestAccounts=True,
                searchQuery="databasenot",
                withAggregations=True,
            )["results"],
            key=lambda x: x["id"],
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["id"], "01936e81-b0ce-7b56-8497-791e505b0d0c")
        self.assertEqual(results[0]["aggregations"]["occurrences"], 1)
        self.assertEqual(results[0]["aggregations"]["sessions"], 0)
        self.assertEqual(results[0]["aggregations"]["users"], 1)

        self.assertEqual(results[1]["id"], "01936e81-f5ce-79b1-99f1-f0e9675fcfef")
        self.assertEqual(results[1]["aggregations"]["occurrences"], 1)
        self.assertEqual(results[1]["aggregations"]["sessions"], 0)
        self.assertEqual(results[1]["aggregations"]["users"], 1)

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_empty_search_query(self):
        results = self._calculate(searchQuery="probs not found")["results"]
        self.assertEqual(len(results), 0)

    @freeze_time("2022-01-10 12:11:00")
    @snapshot_clickhouse_queries
    def test_search_query_with_multiple_search_items(self):
        self.create_events_and_issue(
            issue_id="01936e81-b0ce-7b56-8497-791e505b0d0c",
            fingerprint="fingerprint_DatabaseNotFoundX",
            distinct_ids=[self.distinct_id_one],
            additional_properties={
                "$exception_types": "['DatabaseNotFoundX']",
                "$exception_values": "['this is the same error message']",
                "$exception_sources": "['posthog/clickhouse/client/execute.py']",
            },
        )

        self.create_events_and_issue(
            issue_id="01936e81-f5ce-79b1-99f1-f0e9675fcfef",
            fingerprint="fingerprint_DatabaseNotFoundY",
            distinct_ids=[self.distinct_id_two],
            additional_properties={
                "$exception_types": "['DatabaseNotFoundY']",
                "$exception_values": "['this is the same error message']",
                "$exception_sources": "['posthog/clickhouse/client/execute.py']",
            },
        )
        flush_persons_and_events()

        results = self._calculate(
            filterTestAccounts=True, searchQuery="databasenotfoundX clickhouse/client/execute.py", withAggregations=True
        )["results"]

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "01936e81-b0ce-7b56-8497-791e505b0d0c")
        self.assertEqual(results[0]["aggregations"]["occurrences"], 1)
        self.assertEqual(results[0]["aggregations"]["sessions"], 0)
        self.assertEqual(results[0]["aggregations"]["users"], 1)

    @freeze_time("2022-01-10 12:11:00")
    @snapshot_clickhouse_queries
    def test_search_person_properties(self):
        distinct_id = "david@posthog.com"

        _create_person(
            team=self.team,
            distinct_ids=[distinct_id],
            properties={"email": distinct_id},
            is_identified=True,
        )

        self.create_events_and_issue(
            issue_id="684bd8ae-498f-4548-bc05-e621b5b5b9aa",
            fingerprint="fingerprint_DatabaseNotFoundX",
            distinct_ids=[distinct_id],
        )

        results = self._calculate(searchQuery="david@posthog.com")["results"]

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "684bd8ae-498f-4548-bc05-e621b5b5b9aa")

    @freeze_time("2020-01-10 12:11:00")
    @snapshot_clickhouse_queries
    def test_only_returns_exception_events(self):
        _create_event(
            distinct_id=self.distinct_id_one,
            event="$pageview",
            team=self.team,
            properties={"$exception_issue_id": self.issue_id_one},
        )
        flush_persons_and_events()

        results = self._calculate()["results"]
        self.assertEqual(len(results), 3)

    @freeze_time("2022-01-10 12:11:00")
    @snapshot_clickhouse_queries
    def test_correctly_counts_session_ids(self):
        common_properties = {
            "$exception_issue_id": self.issue_id_one,
            "$exception_fingerprint": self.issue_one_fingerprint,
        }
        _create_event(
            distinct_id=self.distinct_id_one,
            event="$exception",
            team=self.team,
            properties={"$session_id": str(uuid7()), **common_properties},
        )
        _create_event(
            distinct_id=self.distinct_id_one,
            event="$exception",
            team=self.team,
            properties={"$session_id": str(uuid7()), **common_properties},
        )
        # blank string
        _create_event(
            distinct_id=self.distinct_id_one,
            event="$exception",
            team=self.team,
            properties={"$session_id": "", **common_properties},
        )
        flush_persons_and_events()

        results = self._calculate(issueId=self.issue_id_one, withAggregations=True)["results"]
        self.assertEqual(results[0]["id"], self.issue_id_one)
        # only includes valid session ids
        self.assertEqual(results[0]["aggregations"]["sessions"], 2)

    @freeze_time("2022-01-10 12:11:00")
    @snapshot_clickhouse_queries
    def test_correctly_counts_persons(self):
        results = self._calculate(issueId=self.issue_id_one, withAggregations=True)["results"]
        self.assertEqual(results[0]["id"], self.issue_id_one)
        self.assertEqual(results[0]["aggregations"]["users"], 2)

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_hogql_filters(self):
        results = self._calculate(
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.OR_,
                        values=[
                            PersonPropertyFilter(
                                key="email", value="email@posthog.com", operator=PropertyOperator.EXACT
                            ),
                        ],
                    )
                ],
            )
        )["results"]
        # two errors exist for person with distinct_id_two
        self.assertEqual(len(results), 2)

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_ordering(self):
        results = self._calculate(orderBy="last_seen")["results"]
        self.assertEqual([r["id"] for r in results], [self.issue_id_three, self.issue_id_two, self.issue_id_one])

        results = self._calculate(orderBy="first_seen")["results"]
        self.assertEqual([r["id"] for r in results], [self.issue_id_one, self.issue_id_two, self.issue_id_three])

    @freeze_time("2022-01-10T12:11:00")
    def test_status(self):
        resolved_issue = ErrorTrackingIssue.objects.get(id=self.issue_id_one)
        resolved_issue.status = ErrorTrackingIssue.Status.RESOLVED
        resolved_issue.description = "Stale description"
        resolved_issue.severity = ErrorTrackingIssue.Severity.LOW
        resolved_issue.save(update_fields=["status", "description", "severity"])
        sync_issues_to_clickhouse(issue_ids=[self.issue_id_one], team_id=self.team.pk)

        clickhouse_results = self._calculate(status="resolved", issueId=self.issue_id_one)["results"]
        self.assertEqual([result["id"] for result in clickhouse_results], [self.issue_id_one])
        self.assertEqual(clickhouse_results[0]["status"], ErrorTrackingIssue.Status.RESOLVED)

        resolved_issue.status = ErrorTrackingIssue.Status.ACTIVE
        resolved_issue.severity = ErrorTrackingIssue.Severity.CRITICAL
        resolved_issue.name = "Updated TypeError"
        resolved_issue.description = None
        resolved_issue.state_updated_at = now()
        resolved_issue.save(update_fields=["status", "severity", "name", "description", "state_updated_at"])

        results = self._calculate(status="resolved")["results"]
        self.assertNotIn(self.issue_id_one, [result["id"] for result in results])

        results = self._calculate(status="active", issueId=self.issue_id_one)["results"]
        self.assertEqual([r["id"] for r in results], [self.issue_id_one])
        self.assertEqual(results[0]["status"], ErrorTrackingIssue.Status.ACTIVE)
        self.assertEqual(results[0]["severity"], ErrorTrackingIssue.Severity.CRITICAL)
        self.assertEqual(results[0]["name"], "Updated TypeError")
        self.assertIsNone(results[0]["description"])

        results = self._calculate()["results"]
        self.assertEqual([r["id"] for r in results], [self.issue_id_three, self.issue_id_two, self.issue_id_one])

        results = self._calculate(status="all")["results"]
        self.assertEqual([r["id"] for r in results], [self.issue_id_three, self.issue_id_two, self.issue_id_one])

    @freeze_time("2022-01-10T12:11:00")
    def test_expired_postgres_state_uses_clickhouse_state(self):
        ErrorTrackingIssue.objects.filter(id=self.issue_id_one).update(
            status=ErrorTrackingIssue.Status.RESOLVED,
            state_updated_at=now() - timedelta(seconds=61),
        )

        active_response = self._calculate(status="active")
        self.assertIn(self.issue_id_one, [result["id"] for result in active_response["results"]])
        self.assertNotIn("error_tracking_recent_issue_state", active_response["hogql"])

        resolved_results = self._calculate(status="resolved")["results"]
        self.assertNotIn(self.issue_id_one, [result["id"] for result in resolved_results])

    @freeze_time("2022-01-10T12:11:00")
    def test_recent_issue_state_is_scoped_to_team(self):
        ErrorTrackingIssue.objects.filter(id=self.issue_id_one).update(state_updated_at=now())
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        other_issue = ErrorTrackingIssue.objects.create(
            team=other_team,
            status=ErrorTrackingIssue.Status.RESOLVED,
            state_updated_at=now(),
        )

        with self.assertNumQueries(1):
            recent_states = load_recent_issue_states(self.team.pk)

        self.assertEqual(
            [state.issue_id for state in recent_states], [ErrorTrackingIssue.objects.get(id=self.issue_id_one).id]
        )
        self.assertNotIn(other_issue.id, [state.issue_id for state in recent_states])

    @freeze_time("2022-01-10T12:11:00")
    def test_recent_issue_state_skips_overlay_when_bound_exceeded(self):
        ErrorTrackingIssue.objects.bulk_create(
            ErrorTrackingIssue(team=self.team, status=ErrorTrackingIssue.Status.RESOLVED, state_updated_at=now())
            for _ in range(MAX_RECENT_ISSUE_STATES)
        )
        self.assertEqual(len(load_recent_issue_states(self.team.pk)), MAX_RECENT_ISSUE_STATES)

        ErrorTrackingIssue.objects.create(
            team=self.team, status=ErrorTrackingIssue.Status.RESOLVED, state_updated_at=now()
        )
        self.assertEqual(load_recent_issue_states(self.team.pk), [])

    @freeze_time("2022-01-10T12:11:00")
    def test_recent_issue_state_applies_to_more_than_fifty_fingerprints(self):
        for index in range(50):
            fingerprint = f"additional-fingerprint-{index}"
            ErrorTrackingIssueFingerprintV2.objects.create(
                team=self.team,
                issue_id=self.issue_id_one,
                fingerprint=fingerprint,
            )
            _create_event(
                distinct_id=self.distinct_id_one,
                event="$exception",
                team=self.team,
                properties={"$exception_issue_id": self.issue_id_one, "$exception_fingerprint": fingerprint},
            )
        sync_issues_to_clickhouse(issue_ids=[self.issue_id_one], team_id=self.team.pk)
        flush_persons_and_events()
        ErrorTrackingIssue.objects.filter(id=self.issue_id_one).update(
            status=ErrorTrackingIssue.Status.RESOLVED,
            state_updated_at=now(),
        )

        results = self._calculate(status="resolved", withAggregations=True)["results"]

        self.assertEqual([result["id"] for result in results], [self.issue_id_one])
        self.assertEqual(results[0]["aggregations"]["occurrences"], 52)

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_overrides_aggregation(self):
        self.override_fingerprint(self.issue_three_fingerprint, self.issue_id_one)
        results = self._calculate(withAggregations=True, orderBy="occurrences")["results"]
        self.assertEqual(len(results), 2)

        # count is (2 x issue_one) + (1 x issue_three)
        self.assertEqual(results[0]["id"], self.issue_id_one)
        self.assertEqual(results[0]["aggregations"]["occurrences"], 3)

        self.assertEqual(results[1]["id"], self.issue_id_two)
        self.assertEqual(results[1]["aggregations"]["occurrences"], 1)

    def test_issue_id_uses_current_fingerprint_state(self):
        issue_id = "01936e80-f594-7a2e-8545-7bcb491aa61f"
        fingerprint = "event_without_issue_id"
        distinct_id = "event_without_issue_id_user"
        self.create_issue(issue_id, fingerprint)
        _create_event(
            distinct_id=distinct_id,
            event="$exception",
            team=self.team,
            properties={"$exception_fingerprint": fingerprint},
        )
        flush_persons_and_events()

        response = execute_hogql_query(
            "SELECT toString(issue_id), toString(issue_id_v2) FROM events WHERE distinct_id = {distinct_id}",
            team=self.team,
            placeholders={"distinct_id": ast.Constant(value=distinct_id)},
        )

        self.assertEqual(response.results, [(issue_id, issue_id)])

    @freeze_time("2022-01-10T12:11:00")
    def test_user_assignee(self):
        issue_id = "e9ac529f-ac1c-4a96-bd3a-107034368d64"
        self.create_events_and_issue(
            issue_id=issue_id,
            fingerprint="assigned_issue_fingerprint",
            distinct_ids=[self.distinct_id_one],
        )
        flush_persons_and_events()
        ErrorTrackingIssueAssignment.objects.create(issue_id=issue_id, user=self.user, team=self.team)
        ErrorTrackingIssue.objects.filter(id=issue_id).update(state_updated_at=now())

        results = self._calculate(assignee={"type": "user", "id": self.user.pk})["results"]
        self.assertEqual([x["id"] for x in results], [issue_id])

        with freeze_time("2022-01-10T12:11:05"):
            sync_issues_to_clickhouse(issue_ids=[issue_id], team_id=self.team.pk)
            ErrorTrackingIssue.objects.filter(id=issue_id).update(state_updated_at=now() - timedelta(seconds=61))
            results = self._calculate(assignee={"type": "user", "id": self.user.pk})["results"]
        self.assertEqual([x["id"] for x in results], [issue_id])

    @freeze_time("2022-01-10T12:11:00")
    def test_role_assignee(self):
        issue_id = "e9ac529f-ac1c-4a96-bd3a-107034368d64"
        self.create_events_and_issue(
            issue_id=issue_id,
            fingerprint="assigned_issue_fingerprint",
            distinct_ids=[self.distinct_id_one],
        )
        flush_persons_and_events()
        role = Role.objects.create(name="Test Team", organization=self.organization)
        ErrorTrackingIssueAssignment.objects.create(issue_id=issue_id, role=role, team=self.team)
        ErrorTrackingIssue.objects.filter(id=issue_id).update(state_updated_at=now())

        results = self._calculate(assignee={"type": "role", "id": str(role.id)})["results"]
        self.assertEqual([x["id"] for x in results], [issue_id])

        with freeze_time("2022-01-10T12:11:05"):
            sync_issues_to_clickhouse(issue_ids=[issue_id], team_id=self.team.pk)
            ErrorTrackingIssue.objects.filter(id=issue_id).update(state_updated_at=now() - timedelta(seconds=61))
            results = self._calculate(assignee={"type": "role", "id": str(role.id)})["results"]
        self.assertEqual([x["id"] for x in results], [issue_id])

    @freeze_time("2022-01-10T12:11:00")
    def test_unassignment_clears_assignee(self):
        issue_id = "e9ac529f-ac1c-4a96-bd3a-107034368d64"
        self.create_events_and_issue(
            issue_id=issue_id, fingerprint="unassign_issue_fingerprint", distinct_ids=[self.distinct_id_one]
        )
        flush_persons_and_events()

        assignment = ErrorTrackingIssueAssignment.objects.create(issue_id=issue_id, user=self.user, team=self.team)
        with freeze_time("2022-01-10T12:11:01"):
            sync_issues_to_clickhouse(issue_ids=[issue_id], team_id=self.team.pk)

        with freeze_time("2022-01-10T12:11:02"):
            assignment.delete()
            ErrorTrackingIssue.objects.filter(id=issue_id).update(state_updated_at=now())

            results = self._calculate()["results"]
            matching = [r for r in results if r["id"] == issue_id]
            self.assertEqual(len(matching), 1)
            self.assertIsNone(matching[0]["assignee"])

        with freeze_time("2022-01-10T12:11:03"):
            sync_issues_to_clickhouse(issue_ids=[issue_id], team_id=self.team.pk)
            ErrorTrackingIssue.objects.filter(id=issue_id).update(state_updated_at=now() - timedelta(seconds=61))
            results = self._calculate()["results"]
        matching = [r for r in results if r["id"] == issue_id]
        self.assertEqual(len(matching), 1)
        self.assertIsNone(matching[0]["assignee"])

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_issue_filters(self):
        results = self._calculate(
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            ErrorTrackingIssueFilter(
                                key="name", value=[self.issue_name_one], operator=PropertyOperator.EXACT
                            ),
                        ],
                    )
                ],
            )
        )["results"]
        self.assertEqual(len(results), 1)

    @freeze_time("2022-01-10T12:11:00")
    def test_recent_issue_state_applies_before_issue_filters(self):
        ErrorTrackingIssue.objects.filter(id=self.issue_id_one).update(
            name="Updated TypeError",
            severity=ErrorTrackingIssue.Severity.CRITICAL,
            state_updated_at=now(),
        )

        results = self._calculate(
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            ErrorTrackingIssueFilter(
                                key="name", value=["Updated TypeError"], operator=PropertyOperator.EXACT
                            ),
                            ErrorTrackingIssueFilter(
                                key="severity",
                                value=ErrorTrackingIssue.Severity.CRITICAL,
                                operator=PropertyOperator.EXACT,
                            ),
                        ],
                    )
                ],
            )
        )["results"]

        self.assertEqual([result["id"] for result in results], [self.issue_id_one])

    @freeze_time("2022-01-10T12:11:00")
    def test_recent_issue_state_keeps_legacy_events_without_fingerprint_state(self):
        issue_id = "01936e80-f594-7a2e-8545-7bcb491aa620"
        ErrorTrackingIssue.objects.create(
            id=issue_id,
            team=self.team,
            status=ErrorTrackingIssue.Status.RESOLVED,
            severity=ErrorTrackingIssue.Severity.CRITICAL,
            name="Recent unmapped issue",
            state_updated_at=now(),
        )
        _create_event(
            distinct_id="unmapped-fingerprint-user",
            event="$exception",
            team=self.team,
            properties={
                "$exception_issue_id": issue_id,
                "$exception_fingerprint": "fingerprint_without_clickhouse_state",
            },
        )
        flush_persons_and_events()

        results = self._calculate(
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            ErrorTrackingIssueFilter(
                                key="name", value=["Recent unmapped issue"], operator=PropertyOperator.EXACT
                            )
                        ],
                    )
                ],
            )
        )["results"]

        self.assertEqual([result["id"] for result in results], [issue_id])
        self.assertEqual(results[0]["severity"], ErrorTrackingIssue.Severity.CRITICAL)

    @parameterized.expand(
        [
            ("exact", PropertyOperator.EXACT, ErrorTrackingIssue.Severity.HIGH, (issue_id_one,)),
            ("is_set", PropertyOperator.IS_SET, True, (issue_id_one,)),
            ("is_not_set", PropertyOperator.IS_NOT_SET, True, (issue_id_two, issue_id_three)),
        ]
    )
    @freeze_time("2022-01-10T12:11:00")
    def test_issue_severity_filter(self, _name, operator, value, expected_ids):
        ErrorTrackingIssue.objects.filter(id=self.issue_id_one).update(severity=ErrorTrackingIssue.Severity.HIGH)
        sync_issues_to_clickhouse(issue_ids=[self.issue_id_one], team_id=self.team.pk)

        results = self._calculate(
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[ErrorTrackingIssueFilter(key="severity", value=value, operator=operator)],
                    )
                ],
            )
        )["results"]

        self.assertEqual({result["id"] for result in results}, set(expected_ids))
        for result in results:
            expected_severity = ErrorTrackingIssue.Severity.HIGH if result["id"] == self.issue_id_one else None
            self.assertEqual(result["severity"], expected_severity)

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

        builder = ErrorTrackingQueryBuilder(
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                dateRange=DateRange(date_from="-7d"),
                filterGroup=filter_group,
                orderBy="last_seen",
                volumeResolution=1,
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
    def test_event_filter_group_operator(self):
        firefox_issue_id = "01936e80-aa51-746f-aec4-cdf16a5c5333"
        chrome_issue_id = "01936e80-aa51-746f-aec4-cdf16a5c5334"
        safari_issue_id = "01936e80-aa51-746f-aec4-cdf16a5c5335"
        self.create_events_and_issue(
            issue_id=firefox_issue_id,
            fingerprint="firefox_issue_fingerprint",
            distinct_ids=[self.distinct_id_one],
            additional_properties={"$browser": "Firefox"},
        )
        self.create_events_and_issue(
            issue_id=chrome_issue_id,
            fingerprint="chrome_issue_fingerprint",
            distinct_ids=[self.distinct_id_one],
            additional_properties={"$browser": "Chrome"},
        )
        self.create_events_and_issue(
            issue_id=safari_issue_id,
            fingerprint="safari_issue_fingerprint",
            distinct_ids=[self.distinct_id_one],
            additional_properties={"$browser": "Safari"},
        )
        flush_persons_and_events()

        browser_filters = [
            EventPropertyFilter(key="$browser", value=["Firefox"], operator=PropertyOperator.EXACT),
            EventPropertyFilter(key="$browser", value=["Chrome"], operator=PropertyOperator.EXACT),
        ]

        or_results = self._calculate(
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[PropertyGroupFilterValue(type=FilterLogicalOperator.OR_, values=browser_filters)],
            )
        )["results"]
        self.assertEqual({result["id"] for result in or_results}, {firefox_issue_id, chrome_issue_id})

        and_results = self._calculate(
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[PropertyGroupFilterValue(type=FilterLogicalOperator.AND_, values=browser_filters)],
            )
        )["results"]
        self.assertEqual([result["id"] for result in and_results], [])

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_person_id_filter(self):
        person = _create_person(
            team=self.team,
            properties={"email": "arthur@posthog.com"},
            is_identified=True,
        )
        issue_id = "684bd8ae-498f-4548-bc05-e621b5b5b9ab"
        self.create_events_and_issue(
            issue_id=issue_id,
            fingerprint="fingerprint_DatabaseNotFound1",
            distinct_ids=["arthur@posthog.com"],
            person_id=str(person.uuid),
        )
        self.create_events_and_issue(
            issue_id="684bd8ae-498f-4548-bc05-e621b5b5b9ac",
            fingerprint="fingerprint_DatabaseNotFound2",
            distinct_ids=["foo@bar.com"],
        )
        flush_persons_and_events()

        results = self._calculate(personId=str(person.uuid))["results"]

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], issue_id)

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_group_key_filter(self):
        group_a_id = "org:acme"
        group_b_id = "org:widgets"
        project_1_id = "project:alpha"

        issue_id_group_a = "784bd8ae-498f-4548-bc05-e621b5b5b9a1"
        issue_id_group_b = "784bd8ae-498f-4548-bc05-e621b5b5b9a2"
        issue_id_project_1 = "784bd8ae-498f-4548-bc05-e621b5b5b9a3"

        self.create_events_and_issue(
            issue_id=issue_id_group_a,
            fingerprint="fingerprint_group_a",
            distinct_ids=[self.distinct_id_one],
            additional_properties={"$group_0": group_a_id},
        )
        self.create_events_and_issue(
            issue_id=issue_id_group_b,
            fingerprint="fingerprint_group_b",
            distinct_ids=[self.distinct_id_two],
            additional_properties={"$group_0": group_b_id},
        )
        self.create_events_and_issue(
            issue_id=issue_id_project_1,
            fingerprint="fingerprint_project_1",
            distinct_ids=[self.distinct_id_one],
            additional_properties={"$group_1": project_1_id},
        )
        flush_persons_and_events()

        results = self._calculate(groupKey=group_a_id, groupTypeIndex=0)["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], issue_id_group_a)

        results = self._calculate(groupKey=group_b_id, groupTypeIndex=0)["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], issue_id_group_b)

        results = self._calculate(groupKey=project_1_id, groupTypeIndex=1)["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], issue_id_project_1)

        results = self._calculate(groupKey="nonexistent", groupTypeIndex=0)["results"]
        self.assertEqual(len(results), 0)

    @freeze_time("2020-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_first_seen_filters(self):
        cutoff_time = now() - relativedelta(hours=2)

        results = self._calculate(
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            ErrorTrackingIssueFilter(
                                key="first_seen", value=cutoff_time.isoformat(), operator=PropertyOperator.GTE
                            ),
                        ],
                    )
                ],
            )
        )["results"]
        self.assertEqual(len(results), 2)
        self.assertEqual([r["id"] for r in results], [self.issue_id_three, self.issue_id_two])

        results = self._calculate(
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            ErrorTrackingIssueFilter(
                                key="first_seen", value=cutoff_time.isoformat(), operator=PropertyOperator.LT
                            ),
                        ],
                    )
                ],
            )
        )["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual([r["id"] for r in results], [self.issue_id_one])

    @freeze_time("2020-01-12")
    @snapshot_clickhouse_queries
    def test_volume_aggregation_simple(self):
        results = self._calculate(
            volumeResolution=3, dateRange=DateRange(date_from="2020-01-10", date_to="2020-01-11"), withAggregations=True
        )["results"]
        self.assertEqual(len(results), 3)

        ## Make sure resolution is correct
        for result in results:
            aggregations = result["aggregations"]
            self.assertEqual(len(aggregations["volumeRange"]), 3)

        ## Make sure occurrences are correct
        first_aggregations = results[0]["aggregations"]
        self.assertEqual(first_aggregations["volumeRange"], [0, 1, 0])

    @freeze_time("2020-01-12")
    def test_volume_aggregation_counts_only(self):
        # Regression test: volumeResolution=0 (counts only) used to build
        # intDiv(..., 0) bin expressions and fail with an illegal division.
        results = self._calculate(
            volumeResolution=0, dateRange=DateRange(date_from="2020-01-10", date_to="2020-01-11"), withAggregations=True
        )["results"]
        self.assertEqual(len(results), 3)

        for result in results:
            aggregations = result["aggregations"]
            self.assertIsNone(aggregations["volumeRange"])
            self.assertEqual(aggregations["volume_buckets"], [])
            self.assertGreaterEqual(aggregations["occurrences"], 1)

    @freeze_time("2025-05-05")
    @snapshot_clickhouse_queries
    def test_volume_aggregation_advanced(self):
        issue_id = "e9ac529f-ac1c-4a96-bd3a-102334368d64"
        issue_fingerprint = "fingerprint"
        self.create_issue(issue_id, issue_fingerprint)
        for ts in range(0, 24):
            event_properties = {
                "$exception_issue_id": issue_id,
                "$exception_fingerprint": issue_fingerprint,
                "$exception_list": [],
            }
            for distinct_id in range(0, 5):
                event_ts = now() - timedelta(hours=ts)
                _create_event(
                    distinct_id=f"{issue_id}_{ts}_{distinct_id}",
                    event="$exception",
                    team=self.team,
                    properties=event_properties,
                    timestamp=event_ts,
                )
        flush_persons_and_events()

        results = self._calculate(
            volumeResolution=4,
            issueId=issue_id,
            dateRange=DateRange(date_from="2025-05-04", date_to="2025-05-06"),
            withAggregations=True,
        )["results"]
        self.assertEqual(len(results), 1)

        ## Make sure resolution is correct
        for result in results:
            aggregations = result["aggregations"]
            self.assertEqual(len(aggregations["volumeRange"]), 4)

        ## Make sure occurrences are correct
        first_aggregations = results[0]["aggregations"]
        self.assertEqual(sum(first_aggregations["volumeRange"]), 24 * 5)
        # bins are left-closed [start, end), so events on an exact bin boundary land in the next bin
        self.assertEqual(first_aggregations["volumeRange"], [55, 60, 5, 0])

    @parameterized.expand(["issueId", "personId"])
    def test_rejects_malformed_uuid_params(self, field):
        with self.assertRaises(ValidationError):
            self._calculate(**{field: "test-distinct-id"})

    def test_canonicalizes_uuid_params(self):
        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                dateRange=DateRange(),
                orderBy="last_seen",  # pyright: ignore[reportArgumentType]
                volumeResolution=1,
                issueId="01936E7FD7FF7314B2D47627981E34F0",
            ),
        )
        self.assertEqual(runner.query.issueId, "01936e7f-d7ff-7314-b2d4-7627981e34f0")

    def test_requires_error_tracking_viewer_access(self):
        for runner_class in (
            ErrorTrackingQueryRunner,
            ErrorTrackingBreakdownsQueryRunner,
            ErrorTrackingFingerprintProjectionQueryRunner,
            ErrorTrackingIssueCorrelationQueryRunner,
            ErrorTrackingSimilarIssuesQueryRunner,
        ):
            self.assertTrue(issubclass(runner_class, ErrorTrackingQueryRunnerAccessMixin))

        AccessControl.objects.create(team=self.team, resource="error_tracking", access_level="none")
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                dateRange=DateRange(),
                orderBy="last_seen",
                volumeResolution=1,
            ),
        )

        with self.assertRaises(UserAccessControlError):
            runner.validate_query_runner_access(self.user)


class TestSearchTokenizer(TestCase):
    test_cases = [
        (
            "This is a \"quoted string\" and this is 'another one' with some words",
            ["This", "is", "a", "quoted string", "and", "this", "is", "another one", "with", "some", "words"],
        ),
        (
            "Empty quotes: \"\" and '' should be preserved",
            ["Empty", "quotes:", "", "and", "", "should", "be", "preserved"],
        ),
        ("Nested \"quotes 'are' tricky\" to handle", ["Nested", "quotes 'are' tricky", "to", "handle"]),
        (
            "Unmatched quotes: \"open quote and 'partial quote",
            ["Unmatched", "quotes:", "open", "quote", "and", "partial", "quote"],
        ),
        ("Multiple     spaces      between words", ["Multiple", "spaces", "between", "words"]),
        (
            "Special characters: @#$% should be treated as words",
            ["Special", "characters:", "@#$%", "should", "be", "treated", "as", "words"],
        ),
        (
            "Single quotes at \"start\" and 'end' of string",
            ["Single", "quotes", "at", "start", "and", "end", "of", "string"],
        ),
        ('"Entire string is quoted"', ["Entire string is quoted"]),
        ('Escaped quotes: "He said "Hello" to me"', ["Escaped", "quotes:", "He said ", "Hello", "to", "me"]),
    ]

    def test_tokenizer(self):
        for case, output in self.test_cases:
            with self.subTest(case=case):
                tokens = search_tokenizer(case)
                self.assertEqual(tokens, output)
