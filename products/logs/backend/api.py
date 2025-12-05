import json
import base64
import datetime as dt

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import DateRange, LogsQuery, OrderBy3

from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import ExecutionMode

from products.logs.backend.logs_query_runner import CachedLogsQueryResponse, LogsQueryResponse, LogsQueryRunner
from products.logs.backend.sparkline_query_runner import SparklineQueryRunner


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

            # Skip time-slicing optimization when:
            # - live tailing: we're always only looking at the most recent 1-2 minutes
            # - cursor pagination: the cursor marks a continuation point in a single query
            if live_logs_checkpoint or after_cursor:
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

        attribute_type = request.GET.get("attribute_type", "log")
        # I don't know why went with 'log' and 'resource' not 'log_attribute' and 'log_resource_attribute'
        # like the property type, but annoyingly it's hard to update this in clickhouse so we're stuck with it for now
        if attribute_type not in ["log", "resource"]:
            attribute_type = "log"

        try:
            limit = int(limit)
        except ValueError:
            limit = 100

        try:
            offset = int(offset)
        except ValueError:
            offset = 0

        # temporarily exclude resource_attributes from the log attributes results
        # this is because we are currently merging resource attributes into log attributes but will stop soon
        # once we stop merging the attributes here: https://github.com/PostHog/posthog/blob/d55f534193220eee1cd50df2c4465229925a572d/rust/capture-logs/src/log_record.rs#L91
        # and the 7 day retention period has passed, we can remove this code
        # If you see this message after 2026-01-01 tell @frank to do it already
        exclude_expression = "1"
        if attribute_type == "log":
            exclude_expression = """(attribute_key NOT IN (
            SELECT attribute_key FROM posthog.log_attributes2
            WHERE time_bucket >= toStartOfInterval(now() - interval 10 minutes, interval 10 minute)
            AND team_id = %(team_id)s
            AND attribute_type = 'resource'
            AND attribute_key LIKE %(search)s
            ))"""

        results = sync_execute(
            f"""
SELECT
    groupArray(%(limit)d)(attribute_key) as keys,
    count() as total_count
FROM (
    SELECT
        attribute_key,
        sum(attribute_count)
    FROM posthog.log_attributes2
    WHERE time_bucket >= toStartOfInterval(now() - interval 10 minutes, interval 10 minute)
    AND team_id = %(team_id)s
    AND attribute_type = %(attribute_type)s
    AND attribute_key LIKE %(search)s
    AND {exclude_expression}
    GROUP BY team_id, attribute_key
    ORDER BY sum(attribute_count) desc, attribute_key asc
    OFFSET %(offset)d
)
""",
            args={
                "search": f"%{search}%",
                "team_id": self.team.id,
                "limit": limit,
                "offset": offset,
                "attribute_type": attribute_type,
            },
            workload=Workload.LOGS,
            team_id=self.team.id,
        )

        r = []
        if type(results) is not list:
            return Response({"error": "Something went wrong"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        if len(results) > 0 and len(results[0]) > 0:
            for result in results[0][0]:
                entry = {
                    "name": result,
                    "propertyFilterType": "log_attribute",
                }
                r.append(entry)
        return Response({"results": r, "count": results[0][1] + offset}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"], required_scopes=["logs:read"])
    def values(self, request: Request, *args, **kwargs) -> Response:
        search = request.GET.get("value", "")
        key = request.GET.get("key", "")

        attribute_type = request.GET.get("attribute_type", "log")
        if attribute_type not in ["log", "resource"]:
            attribute_type = "log"

        results = sync_execute(
            """
SELECT
    groupArray(attribute_value) as keys
FROM (
    SELECT
        attribute_value,
        sum(attribute_count)
    FROM posthog.log_attributes2
    WHERE time_bucket >= toStartOfInterval(now() - interval 1 hour, interval 10 minute)
    AND team_id = %(team_id)s
    AND attribute_type = %(attribute_type)s
    AND attribute_key = %(key)s
    AND attribute_value LIKE %(search)s
    GROUP BY team_id, attribute_value
    ORDER BY sum(attribute_count) desc, attribute_value asc
    LIMIT 50
)
""",
            args={"key": key, "search": f"%{search}%", "team_id": self.team.id, "attribute_type": attribute_type},
            workload=Workload.LOGS,
            team_id=self.team.id,
        )

        r = []
        if type(results) is not list:
            return Response({"error": "Something went wrong"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        if len(results) > 0 and len(results[0]) > 0:
            for result in results[0][0]:
                entry = {
                    "id": result,
                    "name": result,
                }
                r.append(entry)
        return Response(r, status=status.HTTP_200_OK)
