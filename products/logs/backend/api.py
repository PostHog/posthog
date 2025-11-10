import datetime as dt
import itertools

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import DateRange, LogsQuery

from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode

from products.logs.backend.logs_query_runner import CachedLogsQueryResponse, LogsQueryResponse, LogsQueryRunner
from products.logs.backend.sparkline_query_runner import SparklineQueryRunner


class LogsViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    scope_object = "logs"

    @action(detail=False, methods=["POST"], required_scopes=["error_tracking:read"])
    def query(self, request: Request, *args, **kwargs) -> Response:
        query_data = request.data.get("query", None)
        if query_data is None:
            return Response({"error": "No query provided"}, status=status.HTTP_400_BAD_REQUEST)

        date_range = self.get_model(query_data.get("dateRange"), DateRange)
        logs_query_params = {
            "dateRange": date_range,
            "severityLevels": query_data.get("severityLevels", []),
            "serviceNames": query_data.get("serviceNames", []),
            "orderBy": query_data.get("orderBy"),
            "searchTerm": query_data.get("searchTerm", None),
            "filterGroup": query_data.get("filterGroup", None),
            "limit": min(query_data.get("limit", 1000), 2000),
        }
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
                runner: LogsQueryRunner, slice_length: dt.timedelta
            ) -> tuple[LogsQueryRunner, LogsQueryRunner]:
                """
                Slices a LogsQueryRunner into two query runners
                The first one returns just the `slice_length` most recent logs
                The second one returns the rest of the logs
                """
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
                return LogsQueryRunner(slice_query, self.team), LogsQueryRunner(remainder_query, self.team)

            # if we're searching more than 15 minutes, first fetch the first 1 minutes of logs and see if that hits the limit
            if date_range_length > dt.timedelta(minutes=15):
                recent_runner, runner = runner_slice(runner, dt.timedelta(minutes=1))
                response = recent_runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
                limit -= len(response.results)
                yield from response.results
                if limit <= 0:
                    return
                runner.query.limit = limit

            # otherwise if we're searching more than 4 hours search the next hour
            if date_range_length > dt.timedelta(hours=4):
                recent_runner, runner = runner_slice(runner, dt.timedelta(minutes=60))
                response = recent_runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
                limit -= len(response.results)
                yield from response.results
                if limit <= 0:
                    return
                runner.query.limit = limit

            # otherwise if we're searching more than 24 hours search the next 6 hours
            if date_range_length > dt.timedelta(hours=24):
                recent_runner, runner = runner_slice(runner, dt.timedelta(hours=6))
                response = recent_runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
                limit -= len(response.results)
                yield from response.results
                if limit <= 0:
                    return
                runner.query.limit = limit

            response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
            yield from response.results

        try:
            results = list(itertools.islice(results_generator(query, logs_query_params), logs_query_params["limit"]))
        except Exception as e:
            capture_exception(e)
            raise
            # return Response({"error": "Something went wrong"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"query": query, "results": results}, status=200)

    @action(detail=False, methods=["POST"], required_scopes=["error_tracking:read"])
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
        try:
            response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        except Exception as e:
            capture_exception(e)
            raise
            # return Response({"error": "Something went wrong"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        assert isinstance(response, LogsQueryResponse | CachedLogsQueryResponse)
        return Response(response.results, status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"], required_scopes=["error_tracking:read"])
    def attributes(self, request: Request, *args, **kwargs) -> Response:
        search = request.GET.get("search", "")

        results = sync_execute(
            """
SELECT
    groupArray(attribute_key) as keys
FROM (
    SELECT
        attribute_key,
        sum(attribute_count)
    FROM log_attributes
    WHERE time_bucket >= toStartOfInterval(now() - interval 1 hour, interval 10 minute)
    AND team_id = %(team_id)s
    AND attribute_key LIKE %(search)s
    GROUP BY team_id, attribute_key
    ORDER BY sum(attribute_count) desc, attribute_key asc
    LIMIT 100
)
""",
            args={"search": f"%{search}%", "team_id": self.team.id},
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
                    "propertyFilterType": "log",
                }
                r.append(entry)
        return Response(r, status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"], required_scopes=["error_tracking:read"])
    def values(self, request: Request, *args, **kwargs) -> Response:
        search = request.GET.get("value", "")
        key = request.GET.get("key", "")

        results = sync_execute(
            """
SELECT
    groupArray(attribute_value) as keys
FROM (
    SELECT
        attribute_value,
        sum(attribute_count)
    FROM log_attributes
    WHERE time_bucket >= toStartOfInterval(now() - interval 1 hour, interval 10 minute)
    AND team_id = %(team_id)s
    AND attribute_key = %(key)s
    AND attribute_value LIKE %(search)s
    GROUP BY team_id, attribute_value
    ORDER BY sum(attribute_count) desc, attribute_value asc limit 100
)
""",
            args={"key": key, "search": f"%{search}%", "team_id": self.team.id},
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
