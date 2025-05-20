from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.schema import HogQLQuery, LogsQuery, HogQLFilters, DateRange, IntervalType
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
import datetime
import pytz


class LogsViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    scope_object = "logs"

    @action(detail=False, methods=["POST"], required_scopes=["error_tracking:read"])
    def query(self, request: Request, *args, **kwargs) -> Response:
        query_data = request.data.get("query", None)
        if query_data is None:
            return Response({"error": "No query provided"}, status=status.HTTP_400_BAD_REQUEST)

        order = "ASC" if query_data.get("orderBy") == "earliest" else "DESC"

        query = HogQLQuery(
            query=f"""SELECT
                uuid,
                trace_id,
                span_id,
                body,
                attributes,
                timestamp,
                observed_timestamp,
                severity_text,
                severity_number,
                level,
                resource,
                instrumentation_scope,
                event_name
                FROM logs
                WHERE {{filters}}
                ORDER BY timestamp {order}
            """,
            filters=HogQLFilters(dateRange=self.get_model(query_data.get("dateRange"), DateRange)),
        )
        # query = self.get_model(query_data, LogsQuery)
        runner = HogQLQueryRunner(query, self.team, workload=Workload.LOGS, settings=HogQLGlobalSettings(allow_experimental_object_type=False))

        try:
            response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
            results = []
            for result in response.results:
                results.append(
                    {
                        "uuid": result[0],
                        "trace_id": result[1],
                        "span_id": result[2],
                        "body": result[3],
                        "attributes": result[4],
                        "timestamp": result[5],
                        "observed_timestamp": result[6],
                        "severity_text": result[7],
                        "severity_number": result[8],
                        "level": result[9],
                        "resource": result[10],
                        "instrumentation_scope": result[11],
                        "event_name": result[12],
                    }
                )
            response = LogsQueryResponse(results=results)
        except Exception as e:
            capture_exception(e)
            return Response({"error": "Something went wrong"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # assert isinstance(response, LogsQueryResponse | CachedLogsQueryResponse)

        return Response({"query": query, "results": response.results}, status=200)

    @action(detail=False, methods=["POST"], required_scopes=["error_tracking:read"])
    def sparkline(self, request: Request, *args, **kwargs) -> Response:
        query_data = request.data.get("query", {})
        date_range = self.get_model(query_data.get("dateRange"), DateRange)

        query_date_range = QueryDateRange(
            date_range=date_range,
            team=self.team,
            interval=IntervalType.MINUTE,
            now=datetime.datetime.now(tz=pytz.UTC),
        )

        query = HogQLQuery(query="""
        WITH
            {date_from_start_of_interval} AS start_time_bucket,
            {date_to_start_of_interval} AS end_time_bucket,
            all_minutes AS (
                SELECT
                    dateAdd(minute, number, toDateTime({date_from_start_of_interval})) AS time_bucket
                FROM numbers
                LIMIT toUInt64(dateDiff({interval}, start_time_bucket, end_time_bucket) + 1)
            ),
            actual_counts AS (
                SELECT
                    toStartOfInterval(timestamp, {one_interval_period}) AS time,
                    count() AS event_count
                FROM logs
                WHERE
                    ({filters})
                    AND body LIKE '%%'
                GROUP BY time
            )
        SELECT
            am.time_bucket AS time,
            ifNull(ac.event_count, 0) AS count
        FROM all_minutes AS am
        LEFT JOIN actual_counts AS ac ON am.time_bucket = ac.time
        ORDER BY time asc
        LIMIT 1000
        """,
            filters=HogQLFilters(dateRange=self.get_model(query_data.get("dateRange"), DateRange)),
            values=dict(filters=HogQLFilters(dateRange=self.get_model(query_data.get("dateRange"), DateRange)), **query_date_range.to_placeholders()),
        )

        runner = HogQLQueryRunner(query, self.team, workload=Workload.LOGS, settings=HogQLGlobalSettings(allow_experimental_object_type=False))
        response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        return Response(response.results, status=status.HTTP_200_OK)




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
