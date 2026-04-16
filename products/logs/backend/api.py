import re
import json
import base64
import datetime as dt

from django.core.cache import cache
from django.utils import timezone

from drf_spectacular.utils import extend_schema
from opentelemetry import trace
from pydantic import ValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import (
    DateRange,
    FilterLogicalOperator,
    LogAttributesQuery,
    LogsOrderBy,
    LogsQuery,
    LogValuesQuery,
    PropertyGroupFilter,
)

from posthog.api.mixins import PydanticModelMixin
from posthog.api.property_value_metrics import PROPERTY_VALUES_DURATION
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import get_request_analytics_properties, report_user_action
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.hogql_queries.utils.time_sliced_query import time_sliced_results
from posthog.models import User
from posthog.models.exported_asset import ExportedAsset
from posthog.tasks.exporter import export_asset

from products.logs.backend.alerts_api import LogsAlertViewSet
from products.logs.backend.explain import LogExplainViewSet
from products.logs.backend.has_logs_query_runner import HasLogsQueryRunner
from products.logs.backend.log_attributes_query_runner import LogAttributesQueryRunner
from products.logs.backend.log_values_query_runner import LogValuesQueryRunner
from products.logs.backend.logs_query_runner import CachedLogsQueryResponse, LogsQueryResponse, LogsQueryRunner
from products.logs.backend.services_query_runner import ServicesQueryRunner
from products.logs.backend.sparkline_query_runner import SparklineQueryRunner
from products.logs.backend.views_api import LogsViewViewSet

__all__ = ["LogsViewSet", "LogExplainViewSet", "LogsAlertViewSet", "LogsViewViewSet"]

tracer = trace.get_tracer(__name__)
LOGS_MAX_EXPORT_ROWS = 10_000


# Serializers below are used exclusively for OpenAPI spec generation via
# drf-spectacular. They are NOT used for request validation — the existing
# manual parsing in LogsViewSet is unchanged.

_LOG_PROPERTY_TYPE_CHOICES = ["log", "log_attribute", "log_resource_attribute"]
_LOG_STRING_OPERATORS = ["exact", "is_not", "icontains", "not_icontains", "regex", "not_regex"]
_LOG_NUMERIC_OPERATORS = ["exact", "gt", "lt"]
_LOG_ARRAY_OPERATORS = ["exact", "is_not"]
_LOG_DATE_OPERATORS = ["is_date_exact", "is_date_before", "is_date_after"]
_LOG_EXISTENCE_OPERATORS = ["is_set", "is_not_set"]
_LOG_ALL_OPERATORS = (
    _LOG_STRING_OPERATORS
    + _LOG_NUMERIC_OPERATORS
    + _LOG_ARRAY_OPERATORS
    + _LOG_DATE_OPERATORS
    + _LOG_EXISTENCE_OPERATORS
)


class _DateRangeSerializer(serializers.Serializer):
    date_from = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Start of the date range. Accepts ISO 8601 timestamps or relative formats: -7d, -1h, -1mStart, etc.",
    )
    date_to = serializers.CharField(
        required=False,
        allow_null=True,
        help_text='End of the date range. Same format as date_from. Omit or null for "now".',
    )


class _LogPropertyFilterSerializer(serializers.Serializer):
    key = serializers.CharField(
        help_text='Attribute key. For type "log", use "message". For "log_attribute"/"log_resource_attribute", use the attribute key (e.g. "k8s.container.name").',
    )
    type = serializers.ChoiceField(
        choices=_LOG_PROPERTY_TYPE_CHOICES,
        help_text='"log" filters the log body/message. "log_attribute" filters log-level attributes. "log_resource_attribute" filters resource-level attributes.',
    )
    operator = serializers.ChoiceField(
        choices=_LOG_ALL_OPERATORS,
        help_text="Comparison operator.",
    )
    value = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.",
    )


class _LogsAttributesQuerySerializer(serializers.Serializer):
    search = serializers.CharField(required=False, help_text="Search filter for attribute names")
    attribute_type = serializers.ChoiceField(
        choices=["log", "resource"],
        required=False,
        help_text='Type of attributes: "log" for log attributes, "resource" for resource attributes. Defaults to "log".',
    )
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, help_text="Max results (default: 100)")
    offset = serializers.IntegerField(required=False, min_value=0, help_text="Pagination offset (default: 0)")
    dateRange = _DateRangeSerializer(
        required=False,
        help_text="Date range to search within. Defaults to last hour.",
    )
    serviceNames = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=[],
        help_text="Filter attributes to those appearing in logs from these services.",
    )
    filterGroup = serializers.ListField(
        child=_LogPropertyFilterSerializer(),
        required=False,
        default=[],
        help_text="Property filters to narrow which logs are scanned for attributes.",
    )


class _LogsValuesQuerySerializer(serializers.Serializer):
    key = serializers.CharField(help_text="The attribute key to get values for")
    attribute_type = serializers.ChoiceField(
        choices=["log", "resource"],
        required=False,
        help_text='Type of attribute: "log" or "resource". Defaults to "log".',
    )
    value = serializers.CharField(required=False, help_text="Search filter for attribute values")
    dateRange = _DateRangeSerializer(
        required=False,
        help_text="Date range to search within. Defaults to last hour.",
    )
    serviceNames = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=[],
        help_text="Filter values to those appearing in logs from these services.",
    )
    filterGroup = serializers.ListField(
        child=_LogPropertyFilterSerializer(),
        required=False,
        default=[],
        help_text="Property filters to narrow which logs are scanned for values.",
    )


class _LogsQueryBodySerializer(serializers.Serializer):
    dateRange = _DateRangeSerializer(
        required=False,
        help_text="Date range for the query. Defaults to last hour.",
    )
    severityLevels = serializers.ListField(
        child=serializers.ChoiceField(choices=["trace", "debug", "info", "warn", "error", "fatal"]),
        required=False,
        default=[],
        help_text="Filter by log severity levels.",
    )
    serviceNames = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=[],
        help_text="Filter by service names.",
    )
    orderBy = serializers.ChoiceField(
        choices=["latest", "earliest"],
        required=False,
        help_text="Order results by timestamp.",
    )
    searchTerm = serializers.CharField(required=False, help_text="Full-text search term to filter log bodies.")
    filterGroup = serializers.ListField(
        child=_LogPropertyFilterSerializer(),
        required=False,
        default=[],
        help_text="Property filters for the query.",
    )
    limit = serializers.IntegerField(required=False, default=100, help_text="Max results (1-1000).")
    after = serializers.CharField(required=False, help_text="Pagination cursor from previous response.")


class _LogsQueryRequestSerializer(serializers.Serializer):
    query = _LogsQueryBodySerializer(help_text="The logs query to execute.")


class _LogsSparklineBodySerializer(serializers.Serializer):
    dateRange = _DateRangeSerializer(
        required=False,
        help_text="Date range for the sparkline. Defaults to last hour.",
    )
    severityLevels = serializers.ListField(
        child=serializers.ChoiceField(choices=["trace", "debug", "info", "warn", "error", "fatal"]),
        required=False,
        default=[],
        help_text="Filter by log severity levels.",
    )
    serviceNames = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=[],
        help_text="Filter by service names.",
    )
    searchTerm = serializers.CharField(required=False, help_text="Full-text search term to filter log bodies.")
    filterGroup = serializers.ListField(
        child=_LogPropertyFilterSerializer(),
        required=False,
        default=[],
        help_text="Property filters for the query.",
    )
    sparklineBreakdownBy = serializers.ChoiceField(
        choices=["severity", "service"],
        required=False,
        help_text='Break down sparkline by "severity" (default) or "service".',
    )


class _LogsSparklineRequestSerializer(serializers.Serializer):
    query = _LogsSparklineBodySerializer(help_text="The sparkline query to execute.")


@extend_schema(tags=["logs"])
class LogsViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    scope_object = "logs"

    @staticmethod
    def _normalize_filter_group(filter_group: object) -> dict:
        """Normalize a flat filter array (from MCP) to the nested PropertyGroupFilter structure."""
        if isinstance(filter_group, list):
            if len(filter_group) > 0:
                return {"type": "AND", "values": [{"type": "AND", "values": filter_group}]}
            return {"type": "AND", "values": []}
        if isinstance(filter_group, dict):
            return filter_group
        return {"type": "AND", "values": []}

    @extend_schema(request=_LogsQueryRequestSerializer)
    @action(detail=False, methods=["POST"], required_scopes=["logs:read"])
    def query(self, request: Request, *args, **kwargs) -> Response:
        query_data = request.data.get("query", None)
        if query_data is None:
            return Response({"error": "No query provided"}, status=status.HTTP_400_BAD_REQUEST)

        live_logs_checkpoint = query_data.get("liveLogsCheckpoint", None)
        after_cursor = query_data.get("after", None)
        date_range = self.get_model(query_data.get("dateRange"), DateRange)

        order_by = query_data.get("orderBy")
        # Default to latest instead of erroring on invalid order_by
        if order_by not in (LogsOrderBy.EARLIEST, LogsOrderBy.LATEST):
            order_by = LogsOrderBy.LATEST
        # When using cursor pagination, narrow the date range based on the cursor timestamp.
        # This allows time-slicing optimization to work on progressively smaller ranges
        # as the user pages through results.
        if after_cursor:
            try:
                cursor = json.loads(base64.b64decode(after_cursor).decode("utf-8"))
                cursor_ts = dt.datetime.fromisoformat(cursor["timestamp"])
                if order_by == LogsOrderBy.EARLIEST:
                    # For "earliest" ordering, we're looking for logs AFTER the cursor
                    date_range = DateRange(
                        date_from=cursor_ts.isoformat(),
                        date_to=date_range.date_to,
                    )
                else:
                    # For "latest" ordering (default), we're looking for logs BEFORE the cursor
                    date_range = DateRange(
                        date_from=date_range.date_from,
                        date_to=cursor_ts.isoformat(),
                    )
            except (KeyError, ValueError, json.JSONDecodeError):
                pass  # Invalid cursor format, continue with original date range

        requested_limit = min(query_data.get("limit", 1000), 2000)
        logs_query_params = {
            "dateRange": date_range,
            "severityLevels": query_data.get("severityLevels", []),
            "serviceNames": query_data.get("serviceNames", []),
            "orderBy": order_by,
            "searchTerm": query_data.get("searchTerm", None),
            "filterGroup": self._normalize_filter_group(query_data.get("filterGroup", None)),
            "resourceFingerprint": query_data.get("resourceFingerprint", None),
            "limit": requested_limit + 1,  # Fetch limit plus 1 to see if theres another page
        }
        if live_logs_checkpoint:
            logs_query_params["liveLogsCheckpoint"] = live_logs_checkpoint
        if after_cursor:
            logs_query_params["after"] = after_cursor
        query = LogsQuery(**logs_query_params)
        analytics_props = get_request_analytics_properties(request)

        def make_runner(date_range: DateRange) -> LogsQueryRunner:
            return LogsQueryRunner(LogsQuery(**{**query.model_dump(), "dateRange": date_range}), self.team)

        # Skip time-slicing for live tailing - we're always only looking at the most recent 1-2 minutes
        # Note: cursor pagination no longer skips time-slicing because we narrow the date range
        # to end at the cursor timestamp, allowing time-slicing to work on the remaining range.
        if live_logs_checkpoint:
            response = LogsQueryRunner(query, self.team).run(
                ExecutionMode.CALCULATE_BLOCKING_ALWAYS, analytics_props=analytics_props
            )
            results = list(response.results)
        else:
            results = list(
                time_sliced_results(
                    runner=LogsQueryRunner(query, self.team),
                    order_by_earliest=order_by == LogsOrderBy.EARLIEST,
                    make_runner=make_runner,
                    analytics_props=analytics_props,
                )
            )
        has_more = len(results) > requested_limit
        results = results[:requested_limit]  # Rm the +1 we used to check for another page

        # Generate cursor for next page
        next_cursor = None
        if has_more and results:
            last_result = results[-1]
            cursor_data = {
                "timestamp": last_result["timestamp"].isoformat(),
                "uuid": last_result["uuid"],
            }
            next_cursor = base64.b64encode(json.dumps(cursor_data).encode("utf-8")).decode("utf-8")

        if not live_logs_checkpoint:
            report_user_action(
                request.user,
                "logs query executed",
                {
                    "results_count": len(results),
                    "has_more": has_more,
                    "has_search_term": bool(query_data.get("searchTerm")),
                    "has_filter_group": bool(query_data.get("filterGroup")),
                    "severity_levels_count": len(query_data.get("severityLevels", [])),
                    "service_names_count": len(query_data.get("serviceNames", [])),
                    "is_paginated": bool(after_cursor),
                },
                team=self.team,
                request=request,
            )

        return Response(
            {
                "query": query,
                "results": results,
                "hasMore": has_more,
                "nextCursor": next_cursor,
                "maxExportableLogs": LOGS_MAX_EXPORT_ROWS,
            },
            status=200,
        )

    @extend_schema(request=_LogsSparklineRequestSerializer)
    @action(detail=False, methods=["POST"], required_scopes=["logs:read"])
    def sparkline(self, request: Request, *args, **kwargs) -> Response:
        query_data = request.data.get("query", {})

        query = LogsQuery(
            dateRange=self.get_model(query_data.get("dateRange"), DateRange),
            severityLevels=query_data.get("severityLevels", []),
            serviceNames=query_data.get("serviceNames", []),
            searchTerm=query_data.get("searchTerm", None),
            filterGroup=query_data.get("filterGroup", None),
            resourceFingerprint=query_data.get("resourceFingerprint", None),
            sparklineBreakdownBy=query_data.get("sparklineBreakdownBy"),
        )

        runner = SparklineQueryRunner(team=self.team, query=query)
        response = runner.run(
            ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            analytics_props=get_request_analytics_properties(request),
        )
        assert isinstance(response, LogsQueryResponse | CachedLogsQueryResponse)

        report_user_action(
            request.user,
            "logs sparkline queried",
            {
                "has_search_term": bool(query_data.get("searchTerm")),
                "has_filter_group": bool(query_data.get("filterGroup")),
                "severity_levels_count": len(query_data.get("severityLevels", [])),
                "service_names_count": len(query_data.get("serviceNames", [])),
                "breakdown_by": query_data.get("sparklineBreakdownBy"),
            },
            team=self.team,
            request=request,
        )

        return Response(response.results, status=status.HTTP_200_OK)

    @action(detail=False, methods=["POST"], required_scopes=["logs:read"])
    def services(self, request: Request, *args, **kwargs) -> Response:
        query_data = request.data.get("query", {})

        filter_group = query_data.get("filterGroup", None)
        if filter_group is None:
            filter_group = PropertyGroupFilter(type=FilterLogicalOperator.AND_, values=[])

        query = LogsQuery(
            dateRange=self.get_model(query_data.get("dateRange"), DateRange),
            severityLevels=query_data.get("severityLevels", []),
            serviceNames=query_data.get("serviceNames", []),
            searchTerm=query_data.get("searchTerm", None),
            filterGroup=filter_group,
        )

        runner = ServicesQueryRunner(team=self.team, query=query)
        response = runner.run(
            ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            analytics_props=get_request_analytics_properties(request),
        )
        assert isinstance(response, LogsQueryResponse | CachedLogsQueryResponse)

        report_user_action(
            request.user,
            "logs services queried",
            {
                "services_count": len(response.results.get("services", []))
                if isinstance(response.results, dict)
                else 0,
                "has_search_term": bool(query_data.get("searchTerm")),
                "severity_levels_count": len(query_data.get("severityLevels", [])),
                "service_names_count": len(query_data.get("serviceNames", [])),
            },
            team=self.team,
            request=request,
        )

        return Response(response.results, status=status.HTTP_200_OK)

    @extend_schema(parameters=[_LogsAttributesQuerySerializer])
    @action(detail=False, methods=["GET"], required_scopes=["logs:read"])
    def attributes(self, request: Request, *args, **kwargs) -> Response:
        search = request.GET.get("search", "")
        limit = request.GET.get("limit", 100)
        offset = request.GET.get("offset", 0)

        try:
            dateRange = self.get_model(json.loads(request.GET.get("dateRange", "{}")), DateRange)
        except (json.JSONDecodeError, ValidationError, ValueError):
            # Default to last hour if dateRange is malformed
            dateRange = DateRange(date_from="-1h")

        try:
            serviceNames = json.loads(request.GET.get("serviceNames", "[]"))
        except json.JSONDecodeError:
            serviceNames = []
        try:
            filterGroup = self.get_model(json.loads(request.GET.get("filterGroup", "{}")), PropertyGroupFilter)
        except (json.JSONDecodeError, ValidationError, ValueError, ParseError):
            filterGroup = None

        attributeType = request.GET.get("attribute_type", "log")
        # I don't know why went with 'log' and 'resource' not 'log_attribute' and 'log_resource_attribute'
        # like the property type, but annoyingly it's hard to update this in clickhouse so we're stuck with it for now
        if attributeType not in ["log", "resource"]:
            attributeType = "log"

        try:
            limit = int(limit)
        except ValueError:
            limit = 100

        try:
            offset = int(offset)
        except ValueError:
            offset = 0

        query = LogAttributesQuery(
            dateRange=dateRange,
            attributeType=attributeType,
            search=search,
            limit=limit,
            offset=offset,
            serviceNames=serviceNames,
            filterGroup=filterGroup,
        )

        runner = LogAttributesQueryRunner(team=self.team, query=query)

        result = runner.calculate()
        return Response({"results": result.results, "count": result.count}, status=status.HTTP_200_OK)

    @extend_schema(parameters=[_LogsValuesQuerySerializer])
    @action(detail=False, methods=["GET"], required_scopes=["logs:read"])
    def values(self, request: Request, *args, **kwargs) -> Response:
        with (
            PROPERTY_VALUES_DURATION.labels(endpoint_type="log").time(),
            tracer.start_as_current_span("logs_api_property_values") as span,
        ):
            search = request.GET.get("value", "")
            limit = request.GET.get("limit", 100)
            offset = request.GET.get("offset", 0)
            attributeKey = request.GET.get("key", "")

            span.set_attribute("team_id", self.team.pk)
            span.set_attribute("property_key", attributeKey)
            span.set_attribute("has_value_filter", bool(search))

            if not attributeKey:
                return Response("key is required", status=status.HTTP_400_BAD_REQUEST)

            try:
                dateRange = self.get_model(json.loads(request.GET.get("dateRange", "{}")), DateRange)
            except (json.JSONDecodeError, ValidationError, ValueError):
                # Default to last hour if dateRange is malformed
                dateRange = DateRange(date_from="-1h")

            try:
                serviceNames = json.loads(request.GET.get("serviceNames", "[]"))
            except json.JSONDecodeError:
                serviceNames = []
            try:
                filterGroup = self.get_model(json.loads(request.GET.get("filterGroup", "{}")), PropertyGroupFilter)
            except (json.JSONDecodeError, ValidationError, ValueError, ParseError):
                filterGroup = None

            attributeType = request.GET.get("attribute_type", "log")
            # I don't know why went with 'log' and 'resource' not 'log_attribute' and 'log_resource_attribute'
            # like the property type, but annoyingly it's hard to update this in clickhouse so we're stuck with it for now
            if attributeType not in ["log", "resource"]:
                attributeType = "log"

            span.set_attribute("attribute_type", attributeType)

            try:
                limit = int(limit)
            except ValueError:
                limit = 100

            try:
                offset = int(offset)
            except ValueError:
                offset = 0

            query = LogValuesQuery(
                dateRange=dateRange,
                attributeKey=attributeKey,
                attributeType=attributeType,
                search=search,
                limit=limit,
                offset=offset,
                serviceNames=serviceNames,
                filterGroup=filterGroup,
            )

            runner = LogValuesQueryRunner(team=self.team, query=query)

            result = runner.calculate()
            span.set_attribute("result_count", len(result.results))
            return Response(
                {"results": [r.model_dump() for r in result.results], "refreshing": False},
                status=status.HTTP_200_OK,
            )

    @action(detail=False, methods=["GET"], required_scopes=["logs:read"])
    def has_logs(self, request: Request, *args, **kwargs) -> Response:
        cache_key = f"team:{self.team.id}:has_logs"
        cached = cache.get(cache_key)
        if cached is True:
            report_user_action(
                request.user,
                "logs has_logs checked",
                {"has_logs": True},
                team=self.team,
                request=request,
            )
            return Response({"hasLogs": True}, status=status.HTTP_200_OK)

        runner = HasLogsQueryRunner(self.team)
        has_logs = runner.run()

        # Only cache positive results (once you have logs, you always have logs)
        if has_logs:
            cache.set(cache_key, True, int(dt.timedelta(days=7).total_seconds()))

        report_user_action(
            request.user,
            "logs has_logs checked",
            {"has_logs": has_logs},
            team=self.team,
            request=request,
        )

        return Response({"hasLogs": has_logs}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["POST"], required_scopes=["logs:read"])
    def export(self, request: Request, *args, **kwargs) -> Response:
        query_data = request.data.get("query", None)
        if query_data is None:
            return Response({"error": "No query provided"}, status=status.HTTP_400_BAD_REQUEST)

        columns = request.data.get("columns") or []
        filename = self._generate_export_filename(query_data)

        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.CSV,
            export_context={
                "source": {**query_data, "kind": "LogsQuery", "limit": LOGS_MAX_EXPORT_ROWS},
                "columns": columns,
                "filename": filename,
                "row_limit": LOGS_MAX_EXPORT_ROWS,
            },
            created_by=request.user if isinstance(request.user, User) else None,
        )

        export_asset.delay(asset.id)

        report_user_action(
            request.user,
            "logs export requested",
            {
                "export_id": asset.id,
                "columns_count": len(columns),
                "has_search_term": bool(query_data.get("searchTerm")),
                "service_names_count": len(query_data.get("serviceNames", [])),
            },
            team=self.team,
            request=request,
        )

        return Response(
            {
                "id": asset.id,
                "export_format": asset.export_format,
                "created_at": asset.created_at,
                "has_content": asset.has_content,
                "filename": asset.filename,
            },
            status=status.HTTP_201_CREATED,
        )

    def _generate_export_filename(self, query_data: dict) -> str:
        service_names = query_data.get("serviceNames") or []
        if len(service_names) == 1:
            service_part = re.sub(r"[^a-zA-Z0-9_-]", "-", service_names[0])[:50]
        elif len(service_names) > 1:
            service_part = f"{len(service_names)}-services"
        else:
            service_part = "all-services"

        date_range = query_data.get("dateRange", {})
        date_from = date_range.get("date_from", "")[:10] if date_range.get("date_from") else ""
        date_to = date_range.get("date_to", "")[:10] if date_range.get("date_to") else ""
        if date_from and date_to:
            date_part = f"{date_from}-to-{date_to}"
        elif date_from:
            date_part = f"from-{date_from}"
        else:
            date_part = timezone.now().strftime("%Y-%m-%d")

        return f"logs-{service_part}-{date_part}"
