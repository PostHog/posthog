from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.schema import LogsQuery
from products.logs.backend.logs_query_runner import LogsQueryRunner


# TODO - add serializer/validation
class LogsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "logs"

    @action(detail=False, methods=["POST"], required_scopes=["error_tracking:read"])
    def query(self, request: Request, *args, **kwargs) -> Response:
        query = request.data.get("query", None)
        runner = LogsQueryRunner(LogsQuery(**query), self.team)

        try:
            response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        except Exception as e:
            capture_exception(e)
            return Response({"error": "Something went wrong"}, status=500)

        if response is None:
            return Response({"error": "Failed to fetch logs"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"query": query, "results": response.results}, status=200)
