from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.schema import LogsQuery
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from products.logs.backend.logs_query_runner import (
    CachedLogsQueryResponse,
    LogsQueryResponse,
    LogsQueryRunner,
)
from webbrowser import get
import re
import json


class LogsViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    scope_object = "logs"

    @action(detail=False, methods=["POST"], required_scopes=["error_tracking:read"])
    def query(self, request: Request, *args, **kwargs) -> Response:
        query_data = request.data.get("query", None)
        if query_data is None:
            return Response({"error": "No query provided"}, status=status.HTTP_400_BAD_REQUEST)

        query = self.get_model(query_data, LogsQuery)
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
        from_date = request.data.get("query", {}).get("dateRange", {}).get("date_from", "") or ""
        to_date = request.data.get("query", {}).get("dateRange", {}).get("date_to", "") or ""
        search_term = request.data.get("query", {}).get("searchTerm", "") or ""
        interval = "interval 1 minute"


        print(request.data)
        print(from_date)
        print(to_date)

        # convert date range (e.g. -7d, -4h, -1m etc) to clickhouse query (e.g. - inverval 7 day)
        def convert_date_range(date_range: str) -> str:
            # regex to match date range format
            match = re.match(r"^(-\s*(\d+)\s*([dhm]))$", date_range)
            if match:
                # parse d/m/h to day minute hour
                value = match.group(2)
                unit = match.group(3)
                if unit == "d":
                    return f"- interval {value} day"
                elif unit == "h":
                    return f"- interval {value} hour"
                elif unit == "m":
                    return f"- interval {value} minute"
                else:
                    return ""
            return ""

        from_date = convert_date_range(from_date)
        to_date = convert_date_range(to_date)
        print(convert_date_range(from_date))
        query = f"""
        WITH
            -- 1. Define the overall window boundaries (rounded to the minute)
            toStartOfInterval(now() {from_date}, {interval}) AS start_time_bucket,
            toStartOfInterval(now() {to_date}, {interval}) AS end_time_bucket,

            -- 2. Generate all minute buckets within this window
            all_minutes AS (
                SELECT
                    addMinutes(start_time_bucket, number) AS time_bucket
                FROM system.numbers
                -- Calculate how many minutes are in our 7-day window
                LIMIT toUInt64(dateDiff('minute', start_time_bucket, end_time_bucket) + 1)
            ),

            -- 3. Your original aggregation query
            actual_counts AS (
                SELECT
                    toStartOfInterval(timestamp, {interval}) AS time,
                    count() AS event_count
                FROM logs
                WHERE
                    (timestamp >= now() {from_date} AND timestamp <= now() {to_date}) -- Keep this for filtering source data
                    AND body LIKE '%{search_term}%'
                GROUP BY time
            )

        -- 4. Left join the generated series with your actual counts
        SELECT
            am.time_bucket AS time,
            ifNull(ac.event_count, 0) AS count  -- Use ifNull to replace NULLs with 0
        FROM all_minutes AS am
        LEFT JOIN actual_counts AS ac ON am.time_bucket = ac.time
        ORDER BY time asc
        LIMIT 1000;
        """
        print(query)
        results = sync_execute(
            query,
            workload=Workload.LOGS,
            team_id=self.team.id,
        )

        return Response(results, status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"], required_scopes=["error_tracking:read"])
    def attributes(self, request: Request, *args, **kwargs) -> Response:
        results = sync_execute(
            """
SELECT
    arraySort(arrayDistinct(arrayFlatten(groupArray(JSONDynamicPaths(attributes))))) as flat_unique_paths
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

    @action(detail=False, methods=["GET"], required_scopes=["error_tracking:read"])
    def values(self, request: Request, *args, **kwargs) -> Response:
        value = request.GET.get("value")
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
