from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.schema import LogsQuery, DateRange
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from products.logs.backend.logs_query_runner import (
    CachedLogsQueryResponse,
    LogsQueryResponse,
    LogsQueryRunner,
)
from products.logs.backend.sparkline_query_runner import (
    SparklineQueryRunner,
)


class LogsViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    scope_object = "logs"

    @action(detail=False, methods=["POST"], required_scopes=["error_tracking:read"])
    def query(self, request: Request, *args, **kwargs) -> Response:
        query_data = request.data.get("query", None)
        if query_data is None:
            return Response({"error": "No query provided"}, status=status.HTTP_400_BAD_REQUEST)

        query = LogsQuery(
            dateRange=self.get_model(query_data.get("dateRange"), DateRange),
            severityLevels=query_data.get("severityLevels", []),
            orderBy=query_data.get("orderBy"),
            searchTerm=query_data.get("searchTerm", None),
            filterGroup=query_data.get("filterGroup", None),
        )
        runner = LogsQueryRunner(query, self.team)
        try:
            response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        except Exception as e:
            capture_exception(e)
            return Response({"error": "Something went wrong"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        assert isinstance(response, LogsQueryResponse | CachedLogsQueryResponse)
        return Response({"query": query, "results": response.results}, status=200)

    @action(detail=False, methods=["POST"], required_scopes=["error_tracking:read"])
    def sparkline(self, request: Request, *args, **kwargs) -> Response:
        query_data = request.data.get("query", {})

        query = LogsQuery(
            dateRange=self.get_model(query_data.get("dateRange"), DateRange),
            severityLevels=query_data.get("severityLevels", []),
            searchTerm=query_data.get("searchTerm", None),
            filterGroup=query_data.get("filterGroup", None),
        )

        runner = SparklineQueryRunner(team=self.team, query=query)
        response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        return Response(response.results, status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"], required_scopes=["error_tracking:read"])
    def attributes(self, request: Request, *args, **kwargs) -> Response:
        search = request.GET.get("search", "")

        results = sync_execute(
            """
SELECT
    arrayFilter(
        x -> x like %(search)s,
        arraySort(groupArrayDistinctArrayMerge(attribute_keys)) as keys
    )
FROM log_attributes
WHERE time_bucket >= toStartOfHour(now()) AND time_bucket <= toStartOfHour(now())
AND team_id = %(team_id)s
GROUP BY team_id
LIMIT 1;
""",
            args={"search": f"%{search}%", "team_id": self.team.id},
            workload=Workload.LOGS,
            team_id=self.team.id,
        )

        r = []
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
        search = request.GET.get("search", "")
        key = request.GET.get("key", "")

        results = sync_execute(
            """
SELECT
        arraySort(
            arrayMap(
                (k, v) -> v,
                arrayFilter(
                    (k, v) -> k == %(key)s and v like %(search)s,
                    groupArrayDistinctArrayMerge(attribute_values)
                )
            )
        ) as values
FROM log_attributes
WHERE time_bucket >= toStartOfHour(now()) AND time_bucket <= toStartOfHour(now())
AND team_id = %(team_id)s
GROUP BY team_id
LIMIT 1;
""",
            args={"key": key, "search": f"%{search}%", "team_id": self.team.id},
            workload=Workload.LOGS,
            team_id=self.team.id,
        )

        r = []
        if len(results) > 0 and len(results[0]) > 0:
            for result in results[0][0]:
                entry = {
                    "id": result,
                    "name": result,
                }
                r.append(entry)
        return Response(r, status=status.HTTP_200_OK)
