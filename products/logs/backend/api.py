import json
import base64
import datetime as dt

from pydantic import ValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import DateRange, LogAttributesQuery, LogsQuery, LogValuesQuery, OrderBy3, PropertyGroupFilter

from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.hogql_queries.query_runner import ExecutionMode

from products.logs.backend.explain import LogExplainViewSet
from products.logs.backend.has_logs_query_runner import HasLogsQueryRunner
from products.logs.backend.log_attributes_query_runner import LogAttributesQueryRunner
from products.logs.backend.log_values_query_runner import LogValuesQueryRunner
from products.logs.backend.logs_query_runner import CachedLogsQueryResponse, LogsQueryResponse, LogsQueryRunner
from products.logs.backend.sparkline_query_runner import SparklineQueryRunner

__all__ = ["LogsViewSet", "LogExplainViewSet"]


class LogsViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    scope_object = "logs"

    @action(detail=False, methods=["POST"], required_scopes=["logs:read"])
    def query(self, request: Request, *args, **kwargs) -> Response:
        query_data = request.data.get("query", None)
        if query_data is None:
            return Response({"error": "No query provided"}, status=status.HTTP_400_BAD_REQUEST)

        live_logs_checkpoint = query_data.get("liveLogsCheckpoint", None)
        after_cursor = query_data.get("after", None)
        date_range = self.get_model(query_data.get("dateRange"), DateRange)

        # When using cursor pagination, narrow the date range based on the cursor timestamp.
        # This allows time-slicing optimization to work on progressively smaller ranges
        # as the user pages through results.
        order_by = query_data.get("orderBy")
        if after_cursor:
            try:
                cursor = json.loads(base64.b64decode(after_cursor).decode("utf-8"))
                cursor_ts = dt.datetime.fromisoformat(cursor["timestamp"])
                if order_by == OrderBy3.EARLIEST or order_by == "earliest":
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
            "orderBy": query_data.get("orderBy"),
            "searchTerm": query_data.get("searchTerm", None),
            "filterGroup": query_data.get("filterGroup", None),
            "limit": requested_limit + 1,  # Fetch limit plus 1 to see if theres another page
        }
        if live_logs_checkpoint:
            logs_query_params["liveLogsCheckpoint"] = live_logs_checkpoint
        if after_cursor:
            logs_query_params["after"] = after_cursor
        query = LogsQuery(**logs_query_params)

        def results_generator(query: LogsQuery, logs_query_params: dict):
            """
            A generator that yields results by splitting the query into time slices

            We fetch the first:
                - 3 minutes
                - 1 hour
                - 6 hours

            Of logs at a time, stopping if we hit the limit first (most queries hit it in the first 3 minutes)
            """
            runner = LogsQueryRunner(query, self.team)

            qdr = runner.query_date_range
            date_range_length = qdr.date_to() - qdr.date_from()
            limit = logs_query_params["limit"]

            def runner_slice(
                runner: LogsQueryRunner, slice_length: dt.timedelta, orderBy: OrderBy3 | None
            ) -> tuple[LogsQueryRunner, LogsQueryRunner]:
                """
                Slices a LogsQueryRunner into two query runners
                The first one returns just the `slice_length` most recent logs
                The second one returns the rest of the logs
                """
                if orderBy == OrderBy3.LATEST or orderBy is None:
                    slice_query = LogsQuery(
                        **{
                            **query.model_dump(),
                            "dateRange": DateRange(
                                date_from=(runner.query_date_range.date_to() - slice_length).isoformat(),
                                date_to=runner.query_date_range.date_to().isoformat(),
                            ),
                        }
                    )
                    remainder_query = LogsQuery(
                        **{
                            **query.model_dump(),
                            "dateRange": DateRange(
                                date_from=runner.query_date_range.date_from().isoformat(),
                                date_to=(runner.query_date_range.date_to() - slice_length).isoformat(),
                            ),
                        }
                    )
                else:
                    # invert the logic as we're looking at earliest logs not latest
                    slice_query = LogsQuery(
                        **{
                            **query.model_dump(),
                            "dateRange": DateRange(
                                date_from=runner.query_date_range.date_from().isoformat(),
                                date_to=(runner.query_date_range.date_from() + slice_length).isoformat(),
                            ),
                        }
                    )
                    remainder_query = LogsQuery(
                        **{
                            **query.model_dump(),
                            "dateRange": DateRange(
                                date_to=runner.query_date_range.date_to().isoformat(),
                                date_from=(runner.query_date_range.date_from() + slice_length).isoformat(),
                            ),
                        }
                    )

                return LogsQueryRunner(slice_query, self.team), LogsQueryRunner(remainder_query, self.team)

            # Skip time-slicing for live tailing - we're always only looking at the most recent 1-2 minutes
            # Note: cursor pagination no longer skips time-slicing because we narrow the date range
            # to end at the cursor timestamp, allowing time-slicing to work on the remaining range.
            if live_logs_checkpoint:
                response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
                yield from response.results
                return

            # if we're searching more than 20 minutes, first fetch the first 3 minutes of logs and see if that hits the limit
            if date_range_length > dt.timedelta(minutes=20):
                recent_runner, runner = runner_slice(runner, dt.timedelta(minutes=3), query.orderBy)
                response = recent_runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
                limit -= len(response.results)
                yield from response.results
                if limit <= 0:
                    return
                runner.query.limit = limit

            # otherwise if we're searching more than 4 hours search the next hour
            if date_range_length > dt.timedelta(hours=4):
                recent_runner, runner = runner_slice(runner, dt.timedelta(minutes=60), query.orderBy)
                response = recent_runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
                limit -= len(response.results)
                yield from response.results
                if limit <= 0:
                    return
                runner.query.limit = limit

            # otherwise if we're searching more than 24 hours search the next 6 hours
            if date_range_length > dt.timedelta(hours=24):
                recent_runner, runner = runner_slice(runner, dt.timedelta(hours=6), query.orderBy)
                response = recent_runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
                limit -= len(response.results)
                yield from response.results
                if limit <= 0:
                    return
                runner.query.limit = limit

            response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
            yield from response.results

        results = list(results_generator(query, logs_query_params))
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

        return Response(
            {"query": query, "results": results, "hasMore": has_more, "nextCursor": next_cursor}, status=200
        )

    @action(detail=False, methods=["POST"], required_scopes=["logs:read"])
    def sparkline(self, request: Request, *args, **kwargs) -> Response:
        query_data = request.data.get("query", {})

        query = LogsQuery(
            dateRange=self.get_model(query_data.get("dateRange"), DateRange),
            severityLevels=query_data.get("severityLevels", []),
            serviceNames=query_data.get("serviceNames", []),
            searchTerm=query_data.get("searchTerm", None),
            filterGroup=query_data.get("filterGroup", None),
        )

        runner = SparklineQueryRunner(team=self.team, query=query)
        response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        assert isinstance(response, LogsQueryResponse | CachedLogsQueryResponse)
        return Response(response.results, status=status.HTTP_200_OK)

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

    @action(detail=False, methods=["GET"], required_scopes=["logs:read"])
    def values(self, request: Request, *args, **kwargs) -> Response:
        search = request.GET.get("search", "")
        limit = request.GET.get("limit", 100)
        offset = request.GET.get("offset", 0)
        attributeKey = request.GET.get("key", "")

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
        return Response([r.model_dump() for r in result.results], status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"], required_scopes=["logs:read"])
    def has_logs(self, request: Request, *args, **kwargs) -> Response:
        runner = HasLogsQueryRunner(self.team)
        has_logs = runner.run()
        return Response({"hasLogs": has_logs}, status=status.HTTP_200_OK)
