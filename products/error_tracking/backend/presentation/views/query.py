from __future__ import annotations

import time
from typing import Literal, cast

from django.utils.timezone import now

import structlog
from drf_spectacular.utils import OpenApiResponse
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.schema import (
    CachedErrorTrackingBreakdownsQueryResponse,
    DateRange,
    ErrorTrackingBreakdownsQuery,
    ErrorTrackingIssueAssignee,
    ErrorTrackingQuery,
    EventsQuery,
)

from posthog.hogql.errors import ResolutionError

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import User

from products.error_tracking.backend.facade import (
    api as facade_api,
    contracts,
    queries as query_facade,
    summaries as summaries_facade,
)
from products.error_tracking.backend.facade.query_utils import (
    CONTEXT_EVENT_SELECTS,
    DEFAULT_EVENT_CONTEXT_INCLUDES,
    ISSUE_BREAKDOWN_PROPERTIES,
    ISSUE_BREAKDOWN_QUERY_VALUES,
    ISSUE_FIELDS,
    RELEASE_EVENT_SELECTS,
    TREND_VOLUME_RESOLUTION,
    breakdown_query_date_range,
    build_date_range,
    build_event_selects,
    build_impact,
    build_issue_event_where,
    build_issue_filters,
    build_issue_where,
    build_list_issue,
    build_property_group,
    build_search_query,
    build_sparkline,
    build_top_in_app_frame,
    build_trend,
    compact_dict,
    dedupe_repeated_stacktraces,
    extract_release,
    first_event_window,
    get_page_info,
    map_context_event_properties,
    map_event_row,
    map_issue_breakdown,
    normalize_volume_resolution,
    pick_fields,
    trend_volume_resolution,
)
from products.error_tracking.backend.presentation.views.query_serializers import (
    ErrorTrackingIssueBreakdownSerializer,
    ErrorTrackingIssueDetailSerializer,
    ErrorTrackingIssueEventsQueryRequestSerializer,
    ErrorTrackingIssueEventsResponseSerializer,
    ErrorTrackingIssueQueryRequestSerializer,
    ErrorTrackingIssuesListQueryRequestSerializer,
    ErrorTrackingIssuesListResponseSerializer,
    IssueSummaryStatus,
)

logger = structlog.get_logger(__name__)

# The wait holds a web worker. A read that times out returns `generating`, and generation continues in the background.
ISSUE_SUMMARY_WAIT_SECONDS = 6.0


@frozen
class IssueSummaryRead:
    status: IssueSummaryStatus
    summary: contracts.ErrorTrackingIssueSummary | None


def read_issue_summary(team_id: int, issue_id: str, user: User) -> IssueSummaryRead:
    """Return the stored summary, or wait a bounded time for a first one. A summary failure never fails the read."""
    try:
        # A stale stored summary returns at once while a newer one generates in the background.
        summary = summaries_facade.get_issue_summary(team_id, issue_id, user=user)
        started_at = now()
        started = summaries_facade.start_issue_summary_generation(team_id, issue_id, user=user)
        if summary is None and not started:
            # A worker can save the first summary between the read above and the start, which then returns False.
            summary = summaries_facade.get_issue_summary(team_id, issue_id, user=user)
            if summary is None:
                return IssueSummaryRead(status=IssueSummaryStatus.UNAVAILABLE, summary=None)
        elif summary is None:
            summary = summaries_facade.wait_for_issue_summary(
                team_id,
                issue_id,
                user=user,
                checked_after=started_at,
                timeout_seconds=ISSUE_SUMMARY_WAIT_SECONDS,
            )
    except Exception as error:
        capture_exception(error, {"team_id": team_id, "issue_id": issue_id})
        return IssueSummaryRead(status=IssueSummaryStatus.UNAVAILABLE, summary=None)
    if summary is None:
        return IssueSummaryRead(status=IssueSummaryStatus.GENERATING, summary=None)
    return IssueSummaryRead(status=IssueSummaryStatus.READY, summary=summary)


def summary_payload(summary: contracts.ErrorTrackingIssueSummary) -> dict[str, object]:
    return compact_dict(
        {
            "what_happened": summary.what_happened,
            "likely_cause": summary.likely_cause,
            "who_is_affected": summary.who_is_affected,
            "suggested_next_step": summary.suggested_next_step,
            "category": summary.category.value if summary.category is not None else None,
            "generated_at": summary.generated_at.isoformat(),
        }
    )


class ErrorTrackingQueryViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "error_tracking"

    def _report_issue_read(self, request: ValidatedRequest, issue_id: str, endpoint: str, **properties: object) -> None:
        # The frontend issue events see only the web app, so this is the one record of which issues
        # MCP, CLI and API callers read. A capture failure must not fail the read.
        try:
            report_user_action(
                cast(User, request.user),
                "error_tracking_issue_read",
                {"issue_id": issue_id, "endpoint": endpoint, **properties},
                team=self.team,
                organization=self.team.organization,
                request=request,
            )
        except Exception:
            logger.warning("error_tracking_issue_read_capture_failed", issue_id=issue_id, exc_info=True)

    @validated_request(
        request_serializer=ErrorTrackingIssuesListQueryRequestSerializer,
        responses={200: OpenApiResponse(response=ErrorTrackingIssuesListResponseSerializer)},
        operation_id="error_tracking_query_issues_list_create",
        summary="List compact error tracking issues",
        description="List error tracking issues with typed filters and compact aggregate counts.",
    )
    @action(methods=["POST"], detail=False, url_path="issues", required_scopes=["error_tracking:read"])
    def issues(self, request: ValidatedRequest, **kwargs: object) -> Response:
        params = dict(request.validated_data)
        filters = build_issue_filters(params)
        limit = cast(int, params.get("limit", 10))
        offset = cast(int, params.get("offset", 0))
        assignee = params.get("assignee")
        person_id = params.get("personId")
        volume_resolution = cast(int, params.get("volumeResolution", 0))
        query = ErrorTrackingQuery(
            kind="ErrorTrackingQuery",
            dateRange=DateRange(**build_date_range(params.get("dateRange"))),
            status=cast(str, params.get("status", "active")),
            assignee=ErrorTrackingIssueAssignee(**assignee) if isinstance(assignee, dict) else None,
            filterTestAccounts=cast(bool, params.get("filterTestAccounts", True)),
            searchQuery=build_search_query(params),
            filterGroup=build_property_group(filters),
            orderBy=cast(str, params.get("orderBy", "occurrences")),
            orderDirection=cast(Literal["ASC", "DESC"], params.get("orderDirection", "DESC")),
            limit=limit,
            offset=offset,
            volumeResolution=normalize_volume_resolution(volume_resolution),
            personId=str(person_id) if person_id is not None else None,
            withAggregations=True,
            withFirstEvent=False,
            withLastEvent=False,
            tags={"productKey": "error_tracking"},
        )
        data = query_facade.run_error_tracking_query(self.team, query)
        raw_results_value = data.get("results")
        raw_results: list[object] = raw_results_value if isinstance(raw_results_value, list) else []
        results = [
            build_list_issue(cast(dict[str, object], issue), include_volume=volume_resolution > 0)
            for issue in raw_results[:limit]
        ]
        has_more, next_offset = get_page_info(data, limit, offset)
        payload: dict[str, object] = {"results": results, "hasMore": has_more, "limit": limit, "offset": offset}
        if next_offset is not None:
            payload["nextOffset"] = next_offset
        return Response(payload)

    @validated_request(
        request_serializer=ErrorTrackingIssueQueryRequestSerializer,
        responses={
            200: OpenApiResponse(response=ErrorTrackingIssueDetailSerializer),
            404: OpenApiResponse(description="Issue not found"),
        },
        operation_id="error_tracking_query_issue_create",
        summary="Get compact error tracking issue details",
        description=(
            "Fetch one error tracking issue with impact counts, trend, top in_app frame, first and latest release, and "
            "optional sparkline and event breakdown."
        ),
    )
    @action(methods=["POST"], detail=False, url_path="issue", required_scopes=["error_tracking:read"])
    def issue(self, request: ValidatedRequest, **kwargs: object) -> Response:
        started_at = time.monotonic()
        params = dict(request.validated_data)
        issue_id = str(params["issueId"])
        date_range = build_date_range(params.get("dateRange"))
        include_sparkline = cast(bool, params.get("includeSparkline", False))
        include_breakdown = cast(bool, params.get("includeBreakdown", False))
        filter_test_accounts = cast(bool, params.get("filterTestAccounts", True))
        volume_resolution = cast(int, params.get("volumeResolution", 0))
        if volume_resolution <= 0:
            volume_resolution = 12 if include_sparkline else TREND_VOLUME_RESOLUTION
        volume_resolution = normalize_volume_resolution(volume_resolution)
        issue_basics = facade_api.get_issue_basics(self.team.id, issue_id)
        if issue_basics is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        query = ErrorTrackingQuery(
            kind="ErrorTrackingQuery",
            issueId=issue_id,
            dateRange=DateRange(**date_range),
            filterTestAccounts=filter_test_accounts,
            volumeResolution=trend_volume_resolution(volume_resolution),
            limit=1,
            orderBy="last_seen",
            orderDirection="DESC",
            withAggregations=True,
            withFirstEvent=False,
            withLastEvent=False,
            tags={"productKey": "error_tracking"},
        )
        data = query_facade.run_error_tracking_query(self.team, query)
        raw_results_value = data.get("results")
        raw_results: list[object] = raw_results_value if isinstance(raw_results_value, list) else []
        if not raw_results:
            payload: dict[str, object] = compact_dict(
                {
                    "id": str(issue_basics.id),
                    "name": issue_basics.name,
                    "description": issue_basics.description,
                    "status": issue_basics.status,
                    "severity": issue_basics.severity,
                }
            )
            payload["impact"] = {}
            if include_sparkline:
                payload["sparkline"] = []
            return self._issue_response(
                request,
                issue_id,
                payload,
                started_at=started_at,
                include_breakdown=include_breakdown,
                include_sparkline=include_sparkline,
            )
        issue = cast(dict[str, object], raw_results[0])
        event_properties = self._issue_event_properties(
            request,
            issue_id,
            after=date_range.get("date_from"),
            before=date_range.get("date_to"),
            order="DESC",
            filter_test_accounts=filter_test_accounts,
            select=CONTEXT_EVENT_SELECTS,
        )
        first_event_properties: dict[str, object] = {}
        if (window := first_event_window(issue_basics.first_seen)) is not None:
            # Test accounts stay in, because first_seen counts their events too.
            first_event_properties = self._issue_event_properties(
                request,
                issue_id,
                after=window.after,
                before=window.before,
                order="ASC",
                filter_test_accounts=False,
                select=RELEASE_EVENT_SELECTS,
            )
        payload = compact_dict(
            {
                **pick_fields(issue, ISSUE_FIELDS),
                "top_in_app_frame": build_top_in_app_frame(issue, event_properties),
                "latest_release": extract_release(event_properties),
                "first_release": extract_release(first_event_properties),
                "impact": build_impact(issue),
                "trend": build_trend(issue, issue_basics.first_seen),
                "sparkline": build_sparkline(issue, volume_resolution) if include_sparkline else None,
            }
        )
        if include_breakdown:
            payload["breakdown"] = self._issue_breakdown(request, issue_id, date_range, filter_test_accounts)
        return self._issue_response(
            request,
            issue_id,
            payload,
            started_at=started_at,
            include_breakdown=include_breakdown,
            include_sparkline=include_sparkline,
        )

    def _issue_response(
        self,
        request: ValidatedRequest,
        issue_id: str,
        payload: dict[str, object],
        *,
        started_at: float,
        include_breakdown: bool,
        include_sparkline: bool,
    ) -> Response:
        summary_started_at = time.monotonic()
        summary_read = read_issue_summary(self.team.id, issue_id, cast(User, request.user))
        summary_finished_at = time.monotonic()
        if summary_read.summary is not None:
            payload["summary"] = summary_payload(summary_read.summary)
        payload["summary_status"] = summary_read.status.value
        self._report_issue_read(
            request,
            issue_id,
            "issue",
            include_breakdown=include_breakdown,
            include_sparkline=include_sparkline,
            summary_status=summary_read.status.value,
            # Shows whether starting generation before the ClickHouse queries would shorten first reads.
            facts_ms=round((summary_started_at - started_at) * 1000),
            summary_wait_ms=round((summary_finished_at - summary_started_at) * 1000),
        )
        return Response(payload)

    def _issue_event_properties(
        self,
        request: ValidatedRequest,
        issue_id: str,
        *,
        after: object,
        before: object,
        order: Literal["ASC", "DESC"],
        filter_test_accounts: bool,
        select: list[str],
    ) -> dict[str, object]:
        try:
            context_event_query = EventsQuery(
                kind="EventsQuery",
                event="$exception",
                select=select,
                where=build_issue_where(issue_id),
                filterTestAccounts=filter_test_accounts,
                after=after,
                before=before,
                orderBy=[f"timestamp {order}"],
                limit=1,
                tags={"productKey": "error_tracking"},
            )
            with tags_context(product=Product.ERROR_TRACKING, feature=Feature.QUERY):
                try:
                    event_data = (
                        EventsQueryRunner(team=self.team, query=context_event_query, user=request.user)
                        .calculate()
                        .model_dump(mode="json")
                    )
                except ResolutionError as error:
                    raise ValidationError(str(error)) from error
            if event_data.get("error"):
                logger.warning(
                    "error_tracking_issue_context_query_failed",
                    issue_id=issue_id,
                    team_id=self.team.pk,
                    error=event_data.get("error"),
                )
                return {}
            return map_context_event_properties(event_data)
        except Exception:
            logger.warning(
                "error_tracking_issue_context_query_failed",
                issue_id=issue_id,
                team_id=self.team.pk,
                exc_info=True,
            )
            return {}

    def _issue_breakdown(
        self, request: ValidatedRequest, issue_id: str, date_range: dict[str, object], filter_test_accounts: bool
    ) -> dict[str, object]:
        breakdown_date_range, range_limited = breakdown_query_date_range(date_range, self.team.timezone_info, now())
        # The same query as the breakdowns on the issue page, so agents and people see the same numbers. It goes
        # through the query cache, and HogQL masks restricted properties, so such a dimension comes back empty.
        runner = query_facade.ErrorTrackingBreakdownsQueryRunner(
            team=self.team,
            query=ErrorTrackingBreakdownsQuery(
                kind="ErrorTrackingBreakdownsQuery",
                issueId=issue_id,
                breakdownProperties=ISSUE_BREAKDOWN_PROPERTIES,
                dateRange=DateRange(**breakdown_date_range),
                filterTestAccounts=filter_test_accounts,
                maxValuesPerProperty=ISSUE_BREAKDOWN_QUERY_VALUES,
                tags={"productKey": "error_tracking"},
            ),
        )
        with tags_context(product=Product.ERROR_TRACKING, feature=Feature.QUERY):
            response = runner.run(
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE, user=cast(User, request.user)
            )
        if not isinstance(response, CachedErrorTrackingBreakdownsQueryResponse):
            raise ValidationError("The issue breakdown could not be calculated.")
        breakdown = {
            "date_from": runner.date_from,
            "date_to": runner.date_to,
            "range_limited": range_limited,
            **map_issue_breakdown(response.model_dump(mode="json").get("results") or {}),
        }
        return ErrorTrackingIssueBreakdownSerializer(instance=breakdown).data

    @validated_request(
        request_serializer=ErrorTrackingIssueEventsQueryRequestSerializer,
        responses={
            200: OpenApiResponse(response=ErrorTrackingIssueEventsResponseSerializer),
            404: OpenApiResponse(description="Issue not found"),
        },
        operation_id="error_tracking_query_issue_events_create",
        summary="List sampled exception events for an error tracking issue",
        description="Fetch sampled exception events, stack traces, browser/SDK context, URL, and $session_id values for one issue.",
    )
    @action(methods=["POST"], detail=False, url_path="issue_events", required_scopes=["error_tracking:read"])
    def issue_events(self, request: ValidatedRequest, **kwargs: object) -> Response:
        params = dict(request.validated_data)
        issue_id = str(params["issueId"])
        limit = cast(int, params.get("limit", 1))
        offset = cast(int, params.get("offset", 0))
        if not facade_api.issue_exists_by_id(self.team.id, issue_id):
            return Response(status=status.HTTP_404_NOT_FOUND)
        date_range = build_date_range(params.get("dateRange"))
        requested_includes = params.get("include")
        includes = (
            cast(list[str], requested_includes)
            if isinstance(requested_includes, list)
            else DEFAULT_EVENT_CONTEXT_INCLUDES
        )
        event_selects = build_event_selects(includes)
        query = EventsQuery(
            kind="EventsQuery",
            event="$exception",
            select=event_selects,
            where=build_issue_event_where(issue_id, cast(str | None, params.get("searchQuery"))),
            properties=cast(list[dict[str, object]], params.get("filterGroup", [])),
            filterTestAccounts=cast(bool, params.get("filterTestAccounts", True)),
            after=date_range.get("date_from"),
            before=date_range.get("date_to"),
            orderBy=[f"timestamp {params.get('orderDirection', 'DESC')}"],
            limit=limit,
            offset=offset,
            tags={"productKey": "error_tracking"},
        )
        with tags_context(product=Product.ERROR_TRACKING, feature=Feature.QUERY):
            try:
                data = (
                    EventsQueryRunner(team=self.team, query=query, user=request.user)
                    .calculate()
                    .model_dump(mode="json")
                )
            except ResolutionError as error:
                raise ValidationError(str(error)) from error
        raw_columns = data.get("columns")
        columns = [str(column) for column in raw_columns] if isinstance(raw_columns, list) else event_selects
        raw_results_value = data.get("results")
        raw_results: list[object] = raw_results_value if isinstance(raw_results_value, list) else []
        include_stacktrace = "stacktrace" in includes or "code_variables" in includes
        only_app_frames = cast(bool, params.get("onlyAppFrames", True))
        include_code_variables = "code_variables" in includes
        results = dedupe_repeated_stacktraces(
            [
                map_event_row(row, columns, include_stacktrace, only_app_frames, include_code_variables)
                for row in raw_results[:limit]
            ]
        )
        has_more, next_offset = get_page_info(data, limit, offset)
        payload: dict[str, object] = {"results": results, "hasMore": has_more, "limit": limit, "offset": offset}
        if next_offset is not None:
            payload["nextOffset"] = next_offset
        self._report_issue_read(request, issue_id, "issue_events")
        return Response(payload)
