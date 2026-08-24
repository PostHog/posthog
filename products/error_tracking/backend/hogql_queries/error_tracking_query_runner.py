import datetime
from collections.abc import Sequence
from uuid import UUID
from zoneinfo import ZoneInfo

from django.utils import timezone

from prometheus_client import Histogram

from posthog.schema import CachedErrorTrackingQueryResponse, ErrorTrackingQuery, ErrorTrackingQueryResponse

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.error_tracking_fingerprint_issue_state import (
    PENDING_UPDATES_HOGQL_CONTEXT_KEY,
    RECENT_ISSUE_STATE_HOGQL_CONTEXT_KEY,
)
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models.filters.mixins.utils import cached_property
from posthog.utils import relative_date_parse

from products.error_tracking.backend.hogql_queries.access import ErrorTrackingQueryRunnerAccessMixin
from products.error_tracking.backend.hogql_queries.error_tracking_query_builder import ErrorTrackingQueryBuilder
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_utils import validate_uuid_param
from products.error_tracking.backend.models import ErrorTrackingIssue

RECENT_ISSUE_STATE_WINDOW = datetime.timedelta(seconds=60)
ERROR_TRACKING_QUERY_RECENT_STATE_ROWS = Histogram(
    "error_tracking_query_recent_state_rows",
    "Number of recent authoritative issue-state rows sent with an Error Tracking query",
)


@frozen
class RecentErrorTrackingIssueState:
    issue_id: UUID
    issue_status: str
    issue_name: str | None
    issue_description: str | None
    assigned_user_id: int | None
    assigned_role_id: UUID | None
    state_updated_at: datetime.datetime

    def as_external_row(self) -> dict[str, object]:
        return {
            "issue_id": self.issue_id,
            "issue_status": self.issue_status,
            "issue_name": self.issue_name,
            "issue_description": self.issue_description,
            "assigned_user_id": self.assigned_user_id,
            "assigned_role_id": self.assigned_role_id,
            "state_updated_at": self.state_updated_at,
            "is_present": 1,
        }


class ErrorTrackingQueryRunner(ErrorTrackingQueryRunnerAccessMixin, AnalyticsQueryRunner[ErrorTrackingQueryResponse]):
    query: ErrorTrackingQuery
    cached_response: CachedErrorTrackingQueryResponse
    paginator: HogQLHasMorePaginator
    date_from: datetime.datetime
    date_to: datetime.datetime

    CACHE_VERSION = 4

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.query.issueId = validate_uuid_param(self.query.issueId, "issueId")
        self.query.personId = validate_uuid_param(self.query.personId, "personId")
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset,
        )
        self.date_to = ErrorTrackingQueryRunner.parse_relative_date_to(self.query.dateRange.date_to)
        self.date_from = ErrorTrackingQueryRunner.parse_relative_date_from(
            self.query.dateRange.date_from, default_end=self.date_to
        )

        if self.query.withAggregations is None:
            self.query.withAggregations = True

        # First/last event fetches read every matching event's full properties blob, so they
        # must be opted into explicitly rather than defaulting on.
        if self.query.withFirstEvent is None:
            self.query.withFirstEvent = False

        if self.query.withLastEvent is None:
            self.query.withLastEvent = False

    @cached_property
    def _builder(self) -> ErrorTrackingQueryBuilder:
        return ErrorTrackingQueryBuilder(self.query, self.team, self.date_from, self.date_to)

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        latest_state_updated_at = (
            ErrorTrackingIssue.objects.filter(team_id=self.team.pk, state_updated_at__isnull=False)
            .order_by("-state_updated_at")
            .values_list("state_updated_at", flat=True)
            .first()
        )
        payload["error_tracking_cache_version"] = self.CACHE_VERSION
        payload["error_tracking_state_updated_at"] = (
            latest_state_updated_at.isoformat() if latest_state_updated_at is not None else None
        )
        return payload

    @classmethod
    def parse_relative_date_from(
        cls, date: str | None, default_end: datetime.datetime | None = None
    ) -> datetime.datetime:
        if date == "all":
            return datetime.datetime.now(tz=ZoneInfo("UTC")) - datetime.timedelta(days=365 * 4)
        if date is None:
            # A missing date_from must not silently mean "all time" — that's a 4-year events
            # scan. Anchor the default window to the range end so date_to-only queries stay valid.
            return (default_end or datetime.datetime.now(tz=ZoneInfo("UTC"))) - datetime.timedelta(days=7)
        return relative_date_parse(date, now=datetime.datetime.now(tz=ZoneInfo("UTC")), timezone_info=ZoneInfo("UTC"))

    @classmethod
    def parse_relative_date_to(cls, date: str | None) -> datetime.datetime:
        if not date:
            return datetime.datetime.now(tz=ZoneInfo("UTC"))
        if date == "all":
            raise ValueError("Invalid date range")
        return relative_date_parse(date, ZoneInfo("UTC"), increase=True)

    def to_query(self) -> ast.SelectQuery:
        return self._builder.build_query()

    MAX_PENDING_FINGERPRINT_ISSUE_STATE_UPDATES = 50

    def _hogql_context(self, recent_issue_states: Sequence[RecentErrorTrackingIssueState] = ()) -> HogQLContext:
        ctx = HogQLContext(team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True)
        raw = (self.query.pendingFingerprintIssueStateUpdates or [])[: self.MAX_PENDING_FINGERPRINT_ISSUE_STATE_UPDATES]
        if raw:
            ctx.data_to_ingest[PENDING_UPDATES_HOGQL_CONTEXT_KEY] = [row.model_dump(mode="json") for row in raw]
        if recent_issue_states:
            ctx.data_to_ingest[RECENT_ISSUE_STATE_HOGQL_CONTEXT_KEY] = [
                state.as_external_row() for state in recent_issue_states
            ]
        return ctx

    def _recent_issue_states(self) -> list[RecentErrorTrackingIssueState]:
        with self.timings.measure("error_tracking_query_recent_state_postgres"):
            issues = list(
                ErrorTrackingIssue.objects.filter(
                    team_id=self.team.pk,
                    state_updated_at__gte=timezone.now() - RECENT_ISSUE_STATE_WINDOW,
                ).select_related("assignment")
            )

        states: list[RecentErrorTrackingIssueState] = []
        for issue in issues:
            assignment = getattr(issue, "assignment", None)
            if issue.state_updated_at is None:
                continue
            states.append(
                RecentErrorTrackingIssueState(
                    issue_id=issue.id,
                    issue_status=issue.status,
                    issue_name=issue.name,
                    issue_description=issue.description,
                    assigned_user_id=assignment.user_id if assignment is not None else None,
                    assigned_role_id=assignment.role_id if assignment is not None else None,
                    state_updated_at=issue.state_updated_at,
                )
            )

        ERROR_TRACKING_QUERY_RECENT_STATE_ROWS.observe(len(states))
        return states

    def _calculate(self):
        recent_issue_states = self._recent_issue_states()
        builder = ErrorTrackingQueryBuilder(
            self.query,
            self.team,
            self.date_from,
            self.date_to,
            has_recent_issue_state=bool(recent_issue_states),
        )
        with self.timings.measure("error_tracking_query_hogql_execute"):
            query_result = self.paginator.execute_hogql_query(
                query=builder.build_query(),
                team=self.team,
                query_type="ErrorTrackingQuery",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
                filters=builder.hogql_filters(),
                user=self.user,
                context=self._hogql_context(recent_issue_states),
            )

        columns, results = self._attach_events(query_result.columns or [], query_result.results)

        return ErrorTrackingQueryResponse(
            columns=columns,
            results=builder.process_results(columns, results),
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    # Aggregation queries return only event uuids for first/last event (reading the
    # properties blob inside argMin/argMax decompresses every matching event's blob);
    # the payloads are fetched here with a point lookup over just the selected uuids.
    EVENT_UUID_COLUMNS = {"first_event_uuid": "first_event", "last_event_uuid": "last_event"}

    def _attach_events(self, columns: list[str], results: list) -> tuple[list[str], list]:
        uuid_indexes = [index for index, column in enumerate(columns) if column in self.EVENT_UUID_COLUMNS]
        if not uuid_indexes:
            return columns, results

        uuids = {str(row[index]) for row in results for index in uuid_indexes if row[index] is not None}
        events: dict[str, tuple] = {}
        if uuids:
            with self.timings.measure("error_tracking_query_event_fetch"):
                event_result = execute_hogql_query(
                    query=parse_select(
                        # The explicit LIMIT matters: without one, execute_hogql_query applies
                        # the default 100-row limit and silently drops payloads beyond it.
                        """
                        SELECT uuid, distinct_id, timestamp, properties
                        FROM events
                        WHERE event = '$exception'
                            AND uuid IN {uuids}
                            AND timestamp >= toDateTime({date_from})
                            AND timestamp <= toDateTime({date_to})
                        LIMIT 1 BY uuid
                        LIMIT {event_limit}
                        """,
                        placeholders={
                            "uuids": ast.Constant(value=sorted(uuids)),
                            "date_from": ast.Constant(value=self.date_from),
                            "date_to": ast.Constant(value=self.date_to),
                            "event_limit": ast.Constant(value=len(uuids)),
                        },
                    ),
                    team=self.team,
                    query_type="ErrorTrackingEventFetchQuery",
                    timings=self.timings,
                    modifiers=self.modifiers,
                    limit_context=self.limit_context,
                    user=self.user,
                )
            events = {str(row[0]): row for row in event_result.results}

        new_columns = [self.EVENT_UUID_COLUMNS.get(column, column) for column in columns]
        new_results = []
        for row in results:
            row = list(row)
            for index in uuid_indexes:
                row[index] = events.get(str(row[index])) if row[index] is not None else None
            new_results.append(row)
        return new_columns, new_results
