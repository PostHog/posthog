from datetime import timedelta
from typing import TYPE_CHECKING

from posthog.schema import DateRange, IntervalType

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.utils.breakdowns import BREAKDOWN_OTHER_STRING_LABEL
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange

if TYPE_CHECKING:
    from .marketing_retention_query_runner import MarketingAnalyticsRetentionQueryRunner


def build_summary_query(runner: "MarketingAnalyticsRetentionQueryRunner") -> ast.SelectQuery:
    periods = [runner]
    date_range = runner.query_date_range
    if runner.query.comparePreviousPeriod:
        previous_range = QueryPreviousPeriodDateRange(
            date_range=runner.query.dateRange,
            team=runner.team,
            interval=IntervalType.DAY,
            now=date_range.now_with_timezone,
        )
        start, end = previous_range.date_from(), previous_range.date_to()
        periods.append(
            type(runner)(
                query=runner.query.model_copy(
                    update={
                        "dateRange": DateRange(date_from=start.isoformat(), date_to=end.isoformat(), explicitDate=True)
                    }
                ),
                team=runner.team,
                user=runner.user,
            )
        )

    ctes: dict[str, ast.CTE] = {}
    acquisitions: list[ast.SelectQuery] = []
    for index, period in enumerate(periods):
        acquired = period._build_first_session_select()
        acquired.select.extend(
            [
                ast.Alias(alias="previous", expr=ast.Constant(value=bool(index))),
                ast.Alias(
                    alias="observation_end",
                    expr=ast.Constant(
                        value=period.query_date_range.format_date(
                            min(
                                period.query_date_range.date_to() + timedelta(days=30),
                                date_range.now_with_timezone,
                            )
                        )
                    ),
                ),
                ast.Alias(
                    alias="first_session_id",
                    expr=ast.Call(
                        name="argMin",
                        args=[
                            ast.Field(chain=["events", "$session_id"]),
                            ast.Field(chain=["events", "session", "$start_timestamp"]),
                        ],
                    ),
                ),
            ]
        )
        acquisitions.append(acquired)
    ctes["acquisition"] = ast.CTE(
        name="acquisition",
        expr=ast.SelectSetQuery.create_from_queries(acquisitions, set_operator="UNION ALL")
        if len(acquisitions) > 1
        else acquisitions[0],
        cte_type="subquery",
        materialized=True,
    )
    activity = parse_select(
        """
        SELECT acquisition.actor_id AS actor_id, acquisition.previous AS previous,
            min(events.session.$start_timestamp) AS returned_at
        FROM events
        INNER JOIN acquisition ON events.person_id = acquisition.actor_id
        WHERE events.event = '$pageview' AND notEmpty(events.$session_id)
            AND events.timestamp >= toDateTime({start})
            AND events.timestamp <= toDateTime({end})
            AND events.$session_id != acquisition.first_session_id
            AND toDate(events.session.$start_timestamp) > toDate(acquisition.first_session_at)
            AND events.session.$start_timestamp <= acquisition.first_session_at + INTERVAL 30 DAY
            AND events.session.$start_timestamp <= toDateTime(acquisition.observation_end)
            AND {filters}
        GROUP BY actor_id, previous
        """,
        {
            "start": ast.Constant(value=periods[-1]._cohort_window_start_str),
            "end": ast.Constant(
                value=date_range.format_date(
                    min(date_range.date_to() + timedelta(days=30), date_range.now_with_timezone)
                )
            ),
            "filters": ast.And(exprs=runner._event_filters()) if runner._event_filters() else ast.Constant(value=True),
        },
    )
    assert isinstance(activity, ast.SelectQuery)
    assert activity.select_from and activity.select_from.next_join
    activity.select_from.next_join.join_type = "GLOBAL INNER JOIN"
    ctes["activity"] = ast.CTE(name="activity", expr=activity, cte_type="subquery")
    people = parse_select(
        """
        SELECT acquisition.actor_id AS actor_id, acquisition.breakdown_value AS breakdown_value,
            acquisition.previous AS previous, acquisition.first_session_at AS first_session_at,
            toDateTime(acquisition.observation_end) AS observation_end,
            activity.returned_at AS returned_at
        FROM acquisition
        LEFT JOIN activity ON acquisition.actor_id = activity.actor_id
            AND acquisition.previous = activity.previous
        """
    )
    ctes["people"] = ast.CTE(name="people", expr=people, cte_type="subquery", materialized=True)
    query = parse_select(
        """
        SELECT
            if(breakdown_value IN (
                SELECT breakdown_value FROM people GROUP BY breakdown_value
                ORDER BY countIf(NOT previous) DESC, count() DESC, breakdown_value ASC LIMIT {limit}
            ), breakdown_value, {other}) AS breakdownValue,
            previous,
            count() AS acquired,
            countIf(first_session_at + INTERVAL 7 DAY <= observation_end) AS eligible7d,
            countIf(first_session_at + INTERVAL 7 DAY <= observation_end
                AND returned_at > first_session_at
                AND returned_at <= first_session_at + INTERVAL 7 DAY) AS returned7d,
            countIf(first_session_at + INTERVAL 30 DAY <= observation_end) AS eligible30d,
            countIf(first_session_at + INTERVAL 30 DAY <= observation_end
                AND returned_at > first_session_at) AS returned30d,
            countIf(returned_at > first_session_at) AS returners,
            if(returners > 0,
                medianIf(
                    dateDiff('day', first_session_at, returned_at),
                    returned_at > first_session_at),
                NULL) AS medianReturnDays
        FROM people
        GROUP BY breakdownValue, previous
        ORDER BY previous ASC, acquired DESC, breakdownValue ASC
        LIMIT {row_limit}
        """,
        {
            "limit": ast.Constant(value=runner.breakdown_limit),
            "other": ast.Constant(value=BREAKDOWN_OTHER_STRING_LABEL),
            "row_limit": ast.Constant(value=(runner.breakdown_limit + 1) * len(periods)),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    query.ctes = ctes
    return query
