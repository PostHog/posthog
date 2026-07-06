from __future__ import annotations

from typing import Literal, cast

import structlog
from drf_spectacular.utils import OpenApiResponse
from rest_framework import status, viewsets
from rest_framework.response import Response

from posthog.schema import DateRange, ErrorTrackingIssueAssignee, ErrorTrackingQuery, EventsQuery

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.events_query_runner import EventsQueryRunner

from products.error_tracking.backend.facade import (
    api as facade_api,
    queries as query_facade,
)
from products.error_tracking.backend.facade.query_utils import (
    CONTEXT_EVENT_SELECTS,
    EVENT_SELECTS,
    ISSUE_FIELDS,
    LIST_ISSUE_FIELDS,
    build_date_range,
    build_fingerprint_event_where,
    build_fingerprint_where,
    build_impact,
    build_issue_filters,
    build_property_group,
    build_search_query,
    build_sparkline,
    build_top_in_app_frame,
    compact_dict,
    extract_latest_release,
    get_page_info,
    map_context_event_properties,
    map_event_row,
    normalize_volume_resolution,
    pick_fields,
)
from products.error_tracking.backend.presentation.views.query_serializers import (
    ErrorTrackingIssueDetailSerializer,
    ErrorTrackingIssueEventsQueryRequestSerializer,
    ErrorTrackingIssueEventsResponseSerializer,
    ErrorTrackingIssueQueryRequestSerializer,
    ErrorTrackingIssuesListQueryRequestSerializer,
    ErrorTrackingIssuesListResponseSerializer,
)

logger = structlog.get_logger(__name__)


def build_fingerprint_filter_group(fingerprints: list[str]) -> dict[str, object]:
    filter_group = build_property_group(
        [{"type": "event", "key": "$exception_fingerprint", "operator": "exact", "value": fingerprints}]
    )
    if filter_group is None:
        raise ValueError("build_property_group unexpectedly returned None for a non-empty filter list")
    return filter_group


class ErrorTrackingQueryViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "error_tracking"

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
        limit = cast(int, params.get("limit", 25))
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
        results = [pick_fields(cast(dict[str, object], issue), LIST_ISSUE_FIELDS) for issue in raw_results[:limit]]
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
        description="Fetch one error tracking issue with impact counts, top in_app frame, latest release, and optional sparkline.",
    )
    @action(methods=["POST"], detail=False, url_path="issue", required_scopes=["error_tracking:read"])
    def issue(self, request: ValidatedRequest, **kwargs: object) -> Response:
        params = dict(request.validated_data)
        issue_id = str(params["issueId"])
        date_range = build_date_range(params.get("dateRange"))
        include_sparkline = cast(bool, params.get("includeSparkline", False))
        volume_resolution = cast(int, params.get("volumeResolution", 0))
        if include_sparkline and volume_resolution <= 0:
            volume_resolution = 12
        issue_basics = facade_api.get_issue_basics(self.team.id, issue_id)
        if issue_basics is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        fingerprints = facade_api.resolve_fingerprints(self.team.pk, [issue_id])
        query = ErrorTrackingQuery(
            kind="ErrorTrackingQuery",
            issueId=issue_id,
            dateRange=DateRange(**date_range),
            filterGroup=build_fingerprint_filter_group(fingerprints) if fingerprints else None,
            filterTestAccounts=cast(bool, params.get("filterTestAccounts", True)),
            volumeResolution=normalize_volume_resolution(volume_resolution),
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
                }
            )
            payload["impact"] = {}
            if include_sparkline:
                payload["sparkline"] = []
            return Response(payload)
        issue = cast(dict[str, object], raw_results[0])
        event_properties: dict[str, object] = {}
        if fingerprints:
            try:
                context_event_query = EventsQuery(
                    kind="EventsQuery",
                    event="$exception",
                    select=CONTEXT_EVENT_SELECTS,
                    where=build_fingerprint_where(fingerprints),
                    filterTestAccounts=cast(bool, params.get("filterTestAccounts", True)),
                    after=date_range.get("date_from"),
                    before=date_range.get("date_to"),
                    orderBy=["timestamp DESC"],
                    limit=1,
                    tags={"productKey": "error_tracking"},
                )
                with tags_context(product=Product.ERROR_TRACKING, feature=Feature.QUERY):
                    event_data = (
                        EventsQueryRunner(team=self.team, query=context_event_query).calculate().model_dump(mode="json")
                    )
                if event_data.get("error"):
                    logger.warning(
                        "error_tracking_issue_context_query_failed",
                        issue_id=issue_id,
                        team_id=self.team.pk,
                        error=event_data.get("error"),
                    )
                else:
                    event_properties = map_context_event_properties(event_data)
            except Exception:
                logger.warning(
                    "error_tracking_issue_context_query_failed",
                    issue_id=issue_id,
                    team_id=self.team.pk,
                    exc_info=True,
                )
        payload = compact_dict(
            {
                **pick_fields(issue, ISSUE_FIELDS),
                "top_in_app_frame": build_top_in_app_frame(issue, event_properties),
                "latest_release": extract_latest_release(event_properties),
                "impact": build_impact(issue),
                "sparkline": build_sparkline(issue) if include_sparkline else None,
            }
        )
        return Response(payload)

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
        fingerprints = facade_api.resolve_fingerprints(self.team.pk, [issue_id])
        if not fingerprints:
            return Response({"results": [], "hasMore": False, "limit": limit, "offset": offset})
        query = EventsQuery(
            kind="EventsQuery",
            event="$exception",
            select=EVENT_SELECTS,
            where=build_fingerprint_event_where(fingerprints, cast(str | None, params.get("searchQuery"))),
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
            data = EventsQueryRunner(team=self.team, query=query).calculate().model_dump(mode="json")
        raw_columns = data.get("columns")
        columns = [str(column) for column in raw_columns] if isinstance(raw_columns, list) else EVENT_SELECTS
        raw_results_value = data.get("results")
        raw_results: list[object] = raw_results_value if isinstance(raw_results_value, list) else []
        verbosity = cast(str, params.get("verbosity", "summary"))
        only_app_frames = cast(bool, params.get("onlyAppFrames", True))
        results = [map_event_row(row, columns, verbosity, only_app_frames) for row in raw_results[:limit]]
        has_more, next_offset = get_page_info(data, limit, offset)
        payload: dict[str, object] = {"results": results, "hasMore": has_more, "limit": limit, "offset": offset}
        if next_offset is not None:
            payload["nextOffset"] = next_offset
        return Response(payload)
