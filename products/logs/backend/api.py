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
        results = sync_execute(
            """
SELECT
    arraySort(groupArrayDistinctArrayMerge(attribute_keys)) as flat_unique_paths
FROM log_attributes
WHERE time >= toStartOfHour(now()) AND time <= toStartOfHour(now())
GROUP BY team_id, service_name, time
LIMIT 1000;
""",
            workload=Workload.LOGS,
            team_id=self.team.id,
        )
        return Response(results[0][0], status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"], required_scopes=["error_tracking:read"])
    def values(self, request: Request, *args, **kwargs) -> Response:
        return Response(
            [{"id": "one", "name": "one"}, {"id": "two", "name": "two"}, {"id": "three", "name": "three"}],
            status=status.HTTP_200_OK,
        )

        request.GET.get("value")
        results = sync_execute(
            """
SELECT
    arraySort(arrayFilter(x -> isNotNull(x), arrayDistinct(groupArray(attributes."{value}")))) as flat_unique_values
FROM logs
WHERE (timestamp >= now() - interval 10 minute AND timestamp <= now())
GROUP BY team_id
ORDER BY team_id DESC
LIMIT 1000;
""",
            workload=Workload.LOGS,
            team_id=self.team.id,
        )

        return Response(results[0][0], status=status.HTTP_200_OK)
