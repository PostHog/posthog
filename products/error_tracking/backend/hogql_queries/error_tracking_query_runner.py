import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from posthog.schema import CachedErrorTrackingQueryResponse, ErrorTrackingQuery, ErrorTrackingQueryResponse

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.error_tracking_fingerprint_issue_state import PENDING_UPDATES_HOGQL_CONTEXT_KEY
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models.filters.mixins.utils import cached_property
from posthog.utils import relative_date_parse

from products.error_tracking.backend.hogql_queries.error_tracking_query_builder import ErrorTrackingQueryBuilder
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_utils import validate_uuid_param
from products.error_tracking.backend.logic import list_first_fingerprints


class ErrorTrackingQueryRunner(AnalyticsQueryRunner[ErrorTrackingQueryResponse]):
    query: ErrorTrackingQuery
    cached_response: CachedErrorTrackingQueryResponse
    paginator: HogQLHasMorePaginator
    date_from: datetime.datetime
    date_to: datetime.datetime

    CACHE_VERSION = 3

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
        payload["error_tracking_cache_version"] = self.CACHE_VERSION
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

    def _hogql_context(self) -> HogQLContext:
        ctx = HogQLContext(team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True)
        raw = (self.query.pendingFingerprintIssueStateUpdates or [])[: self.MAX_PENDING_FINGERPRINT_ISSUE_STATE_UPDATES]
        if raw:
            ctx.data_to_ingest[PENDING_UPDATES_HOGQL_CONTEXT_KEY] = [row.model_dump(mode="json") for row in raw]
        return ctx

    def _calculate(self):
        with self.timings.measure("error_tracking_query_hogql_execute"):
            query_result = self.paginator.execute_hogql_query(
                query=self._builder.build_query(),
                team=self.team,
                query_type="ErrorTrackingQuery",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
                filters=self._builder.hogql_filters(),
                user=self.user,
                context=self._hogql_context(),
            )

        columns, results = self._attach_events(query_result.columns or [], query_result.results)

        processed_results = self._attach_canonical_fingerprints(self._builder.process_results(columns, results))

        return ErrorTrackingQueryResponse(
            columns=columns,
            results=processed_results,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def _attach_canonical_fingerprints(self, results: list[dict[str, object]]) -> list[dict[str, object]]:
        issue_ids = list(dict.fromkeys(UUID(str(result["id"])) for result in results))
        if not issue_ids:
            return results

        with self.timings.measure("error_tracking_query_fingerprint_fetch"):
            fingerprints = list_first_fingerprints(team_id=self.team.pk, issue_ids=issue_ids)
        fingerprints_by_issue_id = {fingerprint.issue_id: fingerprint.fingerprint for fingerprint in fingerprints}
        return [{**result, "fingerprint": fingerprints_by_issue_id.get(UUID(str(result["id"])))} for result in results]

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
