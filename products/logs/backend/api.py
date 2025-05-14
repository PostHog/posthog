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
    # TODO - update this
    scope_object = "error_tracking"

    @action(detail=False, methods=["POST"], required_scopes=["error_tracking:read"])
    def query(self, request: Request, *args, **kwargs) -> Response:
        # from products.data_warehouse.backend.hogql_fixer_ai import HogQLQueryFixerTool

        query = request.data.get("query", None)
        # TODO - remove this
        query = LogsQuery(
            # dateRange=DateRange(date_from="2025-01-01", date_to="2025-01-02"),
            limit=2,
            # offset=0,
        )
        runner = LogsQueryRunner(query, self.team)
        # TODO - not sure what to use here
        try:
            # response = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
            response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        # TODO - handle this properly
        except Exception as e:
            capture_exception(e)
            return Response({"error": "Something went wrong"}, status=500)

        if response is None:
            return Response({"error": "Failed to fetch logs"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # error = request.data.get("error", "")

        # if query is None:
        #     return Response(
        #         status=status.HTTP_400_BAD_REQUEST,
        #         data={"message": "No query provided"},
        #     )

        # trace_id = f"fix_hogql_query_{uuid.uuid4()}"
        # user = cast(User, request.user)

        # config: RunnableConfig = {
        #     "configurable": {
        #         "contextual_tools": {
        #             "fix_hogql_query": {
        #                 "hogql_query": query,
        #                 "error_message": error,
        #             }
        #         },
        #         "team_id": self.team_id,
        #         "trace_id": trace_id,
        #         "distinct_id": user.distinct_id,
        #     },
        #     "callbacks": (
        #         [CallbackHandler(posthoganalytics.default_client, distinct_id=user.distinct_id, trace_id=trace_id)]
        #         if posthoganalytics.default_client
        #         else None
        #     ),
        # }

        # result = HogQLQueryFixerTool(_team_id=self.team_id, _context={}).invoke({}, config)

        # if result is None or (isinstance(result, str) and len(result) == 0):
        #     return Response({"trace_id": trace_id, "error": "Could not fix the query"}, status=400)

        return Response({"query": query, "results": response.results}, status=200)

        # return Response(result.model_dump(mode="json"), status=status.HTTP_200_OK)
