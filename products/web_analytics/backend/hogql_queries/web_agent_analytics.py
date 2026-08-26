import urllib.parse as urlparse

from posthog.schema import (
    CachedWebAgentAnalyticsQueryResponse,
    HogQLQueryResponse,
    WebAgentAnalyticsQuery,
    WebAgentAnalyticsQueryResponse,
    WebAgentAnalyticsQueryType,
    WebAgentContentGrouping,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.models.filters.mixins.utils import cached_property

from products.web_analytics.backend.hogql_queries.agent_analytics_definitions import (
    AGENT_CATEGORIES,
    AGENT_CATEGORIES_WITH_CRAWLERS,
    AGENT_EVENTS,
    AGENT_HTTP_EVENT,
    AGENT_NAVIGATION_EVENTS,
    CONVERSION_WINDOW_SECONDS,
    DEFAULT_RESULT_LIMIT,
    INACTIVITY_WINDOW_SECONDS,
    MAX_JOURNEY_STEPS,
    NAVIGATION_WINDOW_SECONDS,
    malformed_path_expr,
    markdown_path_expr,
    normalized_path_expr,
    page_identity_expr,
    referrer_expr,
    response_status_code_expr,
    static_asset_expr,
)
from products.web_analytics.backend.hogql_queries.web_analytics_query_runner import WebAnalyticsQueryRunner


def markdown_retry_pairs(*, md_times: str, html_times: str) -> str:
    return (
        "arrayCount("
        "md_time -> arrayExists("
        "html_time -> dateDiff('second', html_time, md_time) BETWEEN 0 AND {navigation_window_seconds}, "
        f"{html_times}), "
        f"{md_times})"
    )


OVERVIEW_QUERY = r"""
SELECT
    uniqIf(distinct_id, included_request AND {current_period}) AS active_clients,
    uniqIf(bot_name, included_request AND bot_name != '' AND {current_period}) AS agent_families,
    countIf(included_request AND event = {http_event} AND {current_period}) AS server_requests,
    countIf(included_request AND event IN {navigation_events} AND {current_period}) AS client_navigations,
    countIf(included_request AND event = {http_event} AND status > 0 AND {current_period}) AS status_observed,
    countIf(included_request AND event = {http_event} AND status >= 400 AND status < 500 AND {current_period}) AS client_errors,
    uniqIf(distinct_id, included_request AND {previous_period}) AS active_clients_prev,
    countIf(included_request AND event = {http_event} AND {previous_period}) AS server_requests_prev,
    countIf(included_request AND event IN {navigation_events} AND {previous_period}) AS client_navigations_prev,
    countIf(included_request AND event = {http_event} AND status >= 400 AND status < 500 AND {previous_period}) AS client_errors_prev,
    countIf(included_request AND event = {http_event} AND malformed_path AND {current_period}) AS malformed,
    countIf(included_request AND event = {http_event} AND malformed_path AND {previous_period}) AS malformed_prev,
    countIf(included_request AND event = {http_event} AND llms_source AND status = 200 AND {current_period}) AS llms_txt_fetches,
    countIf(agent_scope AND event = {http_event} AND excluded_path AND {current_period}) AS excluded_requests
FROM (
    SELECT
        distinct_id,
        event,
        timestamp,
        `$virt_bot_name` AS bot_name,
        {status} AS status,
        {agent_scope} AS agent_scope,
        {excluded_path} AS excluded_path,
        {malformed_path} AS malformed_path,
        {llms_source_event} AS llms_source,
        {included_request} AS included_request
    FROM events
    WHERE and(event IN {agent_events}, `$virt_is_bot` = true, {periods}, {all_properties})
)
"""

CONVERSION_GOAL_QUERY = r"""
SELECT
    countIf(arrayExists(
        agent_time -> arrayExists(
            goal_time -> dateDiff('second', agent_time, goal_time) BETWEEN 0 AND {conversion_window_seconds},
            current_goal_times
        ),
        current_agent_times
    )) AS converted_agents,
    countIf(arrayExists(
        agent_time -> arrayExists(
            goal_time -> dateDiff('second', agent_time, goal_time) BETWEEN 0 AND {conversion_window_seconds},
            previous_goal_times
        ),
        previous_agent_times
    )) AS converted_agents_prev
FROM (
    SELECT
        distinct_id,
        groupArrayIf(timestamp, {agent_request} AND {current_period}) AS current_agent_times,
        groupArrayIf(timestamp, {agent_request} AND {previous_period}) AS previous_agent_times,
        groupArrayIf(timestamp, {conversion_goal} AND {current_period}) AS current_goal_times,
        groupArrayIf(timestamp, {conversion_goal} AND {previous_period}) AS previous_goal_times
    FROM events
    WHERE and({periods}, ({agent_request} OR {conversion_goal}))
    GROUP BY distinct_id
)
"""

DOUBLE_FETCH_QUERY = (
    r"""
SELECT
    sum(wasted_fetches) AS wasted,
    sum(wasted_fetches_prev) AS wasted_prev,
    uniqIf(page, wasted_fetches > 0) AS waste_pages
FROM (
    SELECT
        distinct_id,
        {page_key} AS page,
"""
    + markdown_retry_pairs(
        md_times="groupArrayIf(timestamp, {is_md_hit} AND {current_period})",
        html_times="groupArrayIf(timestamp, {is_html_hit} AND {current_period})",
    )
    + r""" AS wasted_fetches,
"""
    + markdown_retry_pairs(
        md_times="groupArrayIf(timestamp, {is_md_hit} AND {previous_period})",
        html_times="groupArrayIf(timestamp, {is_html_hit} AND {previous_period})",
    )
    + r""" AS wasted_fetches_prev
    FROM events
    WHERE and(
        event = {http_event},
        `$virt_is_bot` = true,
        {agent_scope},
        {included_path},
        {periods},
        {all_properties}
    )
    GROUP BY distinct_id, page
)
"""
)

ISSUES_QUERY = r"""
SELECT
    {intent_key} AS intent_key,
    any({normalized_path}) AS intent_path,
    countIf({current_period}) AS demand,
    countIf({previous_period}) AS demand_prev,
    uniqIf(properties.$pathname, {current_period}) AS variants,
    arrayElement(topK(1)(`$virt_bot_name`), 1) AS top_agent,
    minIf(timestamp, {current_period}) AS first_seen,
    maxIf(timestamp, {current_period}) AS last_seen
FROM events
WHERE and(
    event = {http_event},
    `$virt_is_bot` = true,
    {agent_scope},
    {is_404},
    {included_path},
    {periods},
    {all_properties}
)
GROUP BY intent_key
ORDER BY demand DESC, intent_key
"""

PAGE_REQUESTS_QUERY = (
    r"""
SELECT
    page,
    sum(fetches) AS fetches,
    sum(md_fetches) AS md_fetches,
    sum(html_fetches) AS html_fetches,
    countIf(client_paired) AS paired_clients
FROM (
    SELECT
        distinct_id,
        {page_key} AS page,
        count() AS fetches,
        countIf({is_md}) AS md_fetches,
        countIf(NOT ({is_md})) AS html_fetches,
"""
    + markdown_retry_pairs(
        md_times="groupArrayIf(timestamp, {is_md})",
        html_times="groupArrayIf(timestamp, NOT ({is_md}))",
    )
    + r""" > 0 AS client_paired
    FROM events
    WHERE and(
        event = {http_event},
        `$virt_is_bot` = true,
        {agent_scope},
        {is_200},
        {included_path},
        {current_period},
        {all_properties}
    )
    GROUP BY distinct_id, page
)
GROUP BY page
ORDER BY fetches DESC, page
"""
)

DEMAND_QUERY = r"""
SELECT
    concat(coalesce(properties.$host, ''), properties.$pathname) AS page,
    coalesce(properties.$host, '') AS host,
    properties.$pathname AS path,
    count() AS demand
FROM events
WHERE and(
    event = {http_event},
    `$virt_is_bot` = true,
    {agent_scope},
    {is_200},
    {included_path},
    {current_period},
    {all_properties}
)
GROUP BY page, host, path
ORDER BY demand DESC, page
"""

ISSUE_VARIANTS_QUERY = r"""
SELECT
    properties.$pathname AS variant,
    count() AS demand,
    arrayElement(topK(1)(`$virt_bot_name`), 1) AS top_agent,
    min(timestamp) AS first_seen
FROM events
WHERE and(
    event = {http_event},
    `$virt_is_bot` = true,
    {agent_scope},
    {is_404},
    {included_path},
    {intent_key} = {selected_intent_key},
    {current_period},
    {all_properties}
)
GROUP BY variant
ORDER BY demand DESC, variant
"""

REQUEST_ANATOMY_QUERY = (
    r"""
SELECT
    agent,
    sum(page_requests) AS requests,
    sum(page_requested_markdown) AS requested_markdown,
    sum(page_retry_pairs) AS retry_pairs,
    sum(page_errors) AS errors
FROM (
    SELECT
        agent,
        distinct_id,
        page,
        count() AS page_requests,
        countIf(is_md) AS page_requested_markdown,
        countIf(is_error) AS page_errors,
"""
    + markdown_retry_pairs(
        md_times="groupArrayIf(timestamp, is_md)",
        html_times="groupArrayIf(timestamp, is_200 AND NOT is_md)",
    )
    + r""" AS page_retry_pairs
    FROM (
        SELECT
            `$virt_bot_name` AS agent,
            distinct_id,
            timestamp,
            {page_key} AS page,
            {is_md} AS is_md,
            {is_200} AS is_200,
            {status} >= 400 AS is_error
        FROM events
        WHERE and(
            event = {http_event},
            `$virt_is_bot` = true,
            {agent_scope},
            {included_path},
            {current_period},
            {all_properties}
        )
    )
    GROUP BY agent, distinct_id, page
)
GROUP BY agent
ORDER BY requests DESC, agent
"""
)

_SESSIONIZED_EVENTS = r"""
SELECT
    distinct_id,
    uuid,
    timestamp,
    agent,
    host,
    path,
    status,
    is_md,
    is_error,
    referrer,
    toString(cityHash64(concat({journey_salt}, distinct_id, agent, host, toString(toUnixTimestamp(
        max(journey_started) OVER (
            PARTITION BY distinct_id, agent, host
            ORDER BY timestamp ASC, uuid ASC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
    ))))) AS journey_key
FROM (
    SELECT
        distinct_id,
        uuid,
        timestamp,
        agent,
        host,
        path,
        status,
        is_md,
        is_error,
        referrer,
        if(
            dateDiff('second', lagInFrame(timestamp, 1, toDateTime(0)) OVER (
                PARTITION BY distinct_id, agent, host
                ORDER BY timestamp ASC, uuid ASC
                ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
            ), timestamp) > {inactivity_window_seconds},
            timestamp,
            toDateTime(0)
        ) AS journey_started
    FROM (
        SELECT
            distinct_id,
            uuid,
            timestamp,
            `$virt_bot_name` AS agent,
            coalesce(properties.$host, '') AS host,
            properties.$pathname AS path,
            {status} AS status,
            {is_md} AS is_md,
            {status} >= 400 AS is_error,
            {referrer} AS referrer
        FROM events
        WHERE and(
            event = {http_event},
            `$virt_is_bot` = true,
            {agent_scope},
            {included_path},
            {current_period},
            {all_properties}
        )
    )
)
"""

TRANSITIONS_QUERY = r"""
SELECT next_path, count() AS requests, countIf(next_status = 404) AS not_found
FROM (
    SELECT
        timestamp,
        path,
        leadInFrame(path) OVER agent_requests AS next_path,
        leadInFrame(timestamp) OVER agent_requests AS next_timestamp,
        leadInFrame(status) OVER agent_requests AS next_status,
        {llms_source_row} AS llms_source
    FROM (
        SELECT
            uuid,
            timestamp,
            `$virt_bot_name` AS agent,
            coalesce(properties.$host, '') AS host,
            properties.$pathname AS path,
            {status} AS status,
            distinct_id
        FROM events
        WHERE and(
            event = {http_event},
            `$virt_is_bot` = true,
            {agent_scope},
            {included_path},
            {current_period},
            {all_properties}
        )
    )
    WINDOW agent_requests AS (
        PARTITION BY distinct_id, agent, host
        ORDER BY timestamp ASC, uuid ASC
        ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING
    )
)
WHERE and(
    llms_source,
    next_path != '',
    next_path != path,
    dateDiff('second', timestamp, next_timestamp) BETWEEN 0 AND {navigation_window_seconds}
)
GROUP BY next_path
ORDER BY requests DESC, next_path
"""

JOURNEY_SUMMARY_QUERY = (
    r"""
SELECT
    count() AS total_journeys,
    round(quantile(0.5)(pages)) AS median_pages,
    round(quantile(0.5)(requests)) AS median_requests,
    round(quantile(0.5)(duration_seconds)) AS median_duration_seconds,
    countIf(errors > 0) AS journeys_with_errors
FROM (
    SELECT
        journey_key,
        uniq(path) AS pages,
        count() AS requests,
        dateDiff('second', min(timestamp), max(timestamp)) AS duration_seconds,
        countIf(is_error) AS errors
    FROM (
"""
    + _SESSIONIZED_EVENTS
    + r"""
    )
    GROUP BY journey_key
)
"""
)

JOURNEYS_QUERY = (
    r"""
SELECT
    journey_key,
    min(timestamp) AS started,
    arrayElement(topK(1)(agent), 1) AS agent,
    any(host) AS host,
    uniq(path) AS pages,
    count() AS requests,
    dateDiff('second', min(timestamp), max(timestamp)) AS duration_seconds,
    countIf(is_error) AS errors
FROM (
"""
    + _SESSIONIZED_EVENTS
    + r"""
)
GROUP BY journey_key
ORDER BY started DESC, journey_key
"""
)

JOURNEY_DETAIL_QUERY = (
    r"""
SELECT
    timestamp,
    path,
    status,
    if(is_md, 'markdown', 'html') AS format,
    referrer,
    multiIf(
        prev_path = '', 'start',
        timestamp = prev_timestamp, 'parallel',
        referrer != '' AND path(referrer) = prev_path, 'confirmed',
        'sequential'
    ) AS transition
FROM (
    SELECT
        timestamp,
        path,
        status,
        is_md,
        referrer,
        lagInFrame(path, 1, '') OVER journey_steps AS prev_path,
        lagInFrame(timestamp) OVER journey_steps AS prev_timestamp
    FROM (
"""
    + _SESSIONIZED_EVENTS
    + r"""
    )
    WHERE journey_key = {selected_journey_key}
    WINDOW journey_steps AS (
        PARTITION BY journey_key
        ORDER BY timestamp ASC, uuid ASC
        ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
    )
)
ORDER BY timestamp ASC
"""
)

QUERY_TEMPLATES = {
    WebAgentAnalyticsQueryType.OVERVIEW: OVERVIEW_QUERY,
    WebAgentAnalyticsQueryType.ISSUES: ISSUES_QUERY,
    WebAgentAnalyticsQueryType.PAGE_REQUESTS: PAGE_REQUESTS_QUERY,
    WebAgentAnalyticsQueryType.TRANSITIONS: TRANSITIONS_QUERY,
    WebAgentAnalyticsQueryType.DEMAND: DEMAND_QUERY,
    WebAgentAnalyticsQueryType.ISSUE_VARIANTS: ISSUE_VARIANTS_QUERY,
    WebAgentAnalyticsQueryType.REQUEST_ANATOMY: REQUEST_ANATOMY_QUERY,
    WebAgentAnalyticsQueryType.JOURNEY_SUMMARY: JOURNEY_SUMMARY_QUERY,
    WebAgentAnalyticsQueryType.JOURNEYS: JOURNEYS_QUERY,
    WebAgentAnalyticsQueryType.JOURNEY_DETAIL: JOURNEY_DETAIL_QUERY,
}

REQUIRED_ARGUMENTS = {
    WebAgentAnalyticsQueryType.ISSUE_VARIANTS: "intentKey",
    WebAgentAnalyticsQueryType.JOURNEY_DETAIL: "journeyKey",
}


class WebAgentAnalyticsQueryRunner(WebAnalyticsQueryRunner[WebAgentAnalyticsQueryResponse]):
    query: WebAgentAnalyticsQuery
    cached_response: CachedWebAgentAnalyticsQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        limit = self.query.limit or DEFAULT_RESULT_LIMIT
        if self.query.queryType == WebAgentAnalyticsQueryType.JOURNEY_DETAIL:
            limit = min(limit, MAX_JOURNEY_STEPS)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY, limit=limit, offset=self.query.offset
        )

    def _agent_categories(self) -> ast.Tuple:
        categories = AGENT_CATEGORIES_WITH_CRAWLERS if self.query.includeCrawlers else AGENT_CATEGORIES
        return ast.Tuple(exprs=[ast.Constant(value=category) for category in categories])

    def _llms_source_expr(self, *, host: str, path: str) -> ast.Expr:
        parsed_url = urlparse.urlparse(self.query.llmsTxtUrl or "")
        source_path = parsed_url.path or "/llms.txt"
        source_host = (parsed_url.hostname or "").lower()
        path_expr = parse_expr(
            "{path} = {source_path}",
            placeholders={"path": parse_expr(path), "source_path": ast.Constant(value=source_path)},
        )
        if not source_host:
            return path_expr
        return parse_expr(
            "{path_match} AND lower(coalesce({host}, '')) = {source_host}",
            placeholders={
                "path_match": path_expr,
                "host": parse_expr(host),
                "source_host": ast.Constant(value=source_host),
            },
        )

    @cached_property
    def _placeholders(self) -> dict[str, ast.Expr]:
        status = response_status_code_expr()
        is_200 = parse_expr("{status} = 200", placeholders={"status": status})
        is_md = markdown_path_expr()
        excluded_path = static_asset_expr()
        included_path = ast.Not(expr=excluded_path)
        agent_scope = parse_expr(
            "`$virt_traffic_category` IN {agent_categories}",
            placeholders={"agent_categories": self._agent_categories()},
        )
        normalized_path = (
            normalized_path_expr()
            if self.query.contentGrouping != WebAgentContentGrouping.EXACT
            else ast.Field(chain=["properties", "$pathname"])
        )
        agent_request = parse_expr(
            "event IN {agent_events} AND `$virt_is_bot` = true AND {agent_scope} AND {included_path} AND {all_properties}",
            placeholders={
                "agent_events": ast.Tuple(exprs=[ast.Constant(value=event) for event in AGENT_EVENTS]),
                "agent_scope": agent_scope,
                "included_path": included_path,
                "all_properties": self.all_properties(),
            },
        )

        return {
            "agent_events": ast.Tuple(exprs=[ast.Constant(value=event) for event in AGENT_EVENTS]),
            "navigation_events": ast.Tuple(exprs=[ast.Constant(value=event) for event in AGENT_NAVIGATION_EVENTS]),
            "http_event": ast.Constant(value=AGENT_HTTP_EVENT),
            "agent_scope": agent_scope,
            "agent_request": agent_request,
            "current_period": self._current_period_expression("timestamp"),
            "previous_period": self._previous_period_expression("timestamp"),
            "periods": self._periods_expression("timestamp"),
            "all_properties": self.all_properties(),
            "status": status,
            "is_404": parse_expr("{status} = 404", placeholders={"status": status}),
            "is_200": is_200,
            "is_md": is_md,
            "is_md_hit": parse_expr("{is_200} AND {is_md}", placeholders={"is_200": is_200, "is_md": is_md}),
            "is_html_hit": parse_expr("{is_200} AND NOT ({is_md})", placeholders={"is_200": is_200, "is_md": is_md}),
            "malformed_path": malformed_path_expr(),
            "excluded_path": excluded_path,
            "included_path": included_path,
            "included_request": ast.And(exprs=[agent_scope, included_path]),
            "normalized_path": normalized_path,
            "page_key": page_identity_expr(),
            "intent_key": parse_expr(
                "concat(coalesce(properties.$host, ''), {normalized_path})",
                placeholders={"normalized_path": normalized_path},
            ),
            "selected_intent_key": ast.Constant(value=self.query.intentKey or ""),
            "conversion_goal": self.conversion_goal_expr or ast.Constant(value=False),
            "conversion_window_seconds": ast.Constant(value=CONVERSION_WINDOW_SECONDS),
            "navigation_window_seconds": ast.Constant(value=NAVIGATION_WINDOW_SECONDS),
            "inactivity_window_seconds": ast.Constant(value=INACTIVITY_WINDOW_SECONDS),
            "referrer": referrer_expr(),
            "journey_salt": ast.Constant(value=str(self.team.uuid)),
            "selected_journey_key": ast.Constant(value=self.query.journeyKey or ""),
            "llms_source_event": self._llms_source_expr(host="properties.$host", path="properties.$pathname"),
            "llms_source_row": self._llms_source_expr(host="host", path="path"),
        }

    def _parse(self, template: str) -> ast.SelectQuery:
        query = parse_select(template, timings=self.timings, placeholders=self._placeholders)
        assert isinstance(query, ast.SelectQuery)
        return query

    def to_query(self) -> ast.SelectQuery:
        required = REQUIRED_ARGUMENTS.get(self.query.queryType)
        if required and not getattr(self.query, required):
            raise QueryError(f"{required} is required for {self.query.queryType.value}")
        with self.timings.measure("web_agent_analytics_query"):
            return self._parse(QUERY_TEMPLATES[self.query.queryType])

    def _execute(self, template: str, query_type: str) -> HogQLQueryResponse:
        return execute_hogql_query(
            query_type=f"web_agent_analytics_{query_type}",
            query=self._parse(template),
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

    def _supplementary_responses(self) -> list[HogQLQueryResponse]:
        if self.query.queryType != WebAgentAnalyticsQueryType.OVERVIEW:
            return []
        responses = [self._execute(DOUBLE_FETCH_QUERY, "double_fetch")]
        if self.query.conversionGoal:
            responses.append(self._execute(CONVERSION_GOAL_QUERY, "conversion_goal"))
        return responses

    def _calculate(self) -> WebAgentAnalyticsQueryResponse:
        response = self.paginator.execute_hogql_query(
            query=self.to_query(),
            query_type=f"web_agent_analytics_{self.query.queryType.value}",
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
        )
        columns = list(response.columns or [])
        types = list(response.types or [])
        results = [list(row) for row in self.paginator.results]
        hogql_parts = [response.hogql]

        for supplement in self._supplementary_responses():
            columns.extend(supplement.columns or [])
            types.extend(supplement.types or [])
            supplement_row = list(supplement.results[0]) if supplement.results else []
            results = [[*(results[0] if results else []), *supplement_row]]
            hogql_parts.append(supplement.hogql)

        return WebAgentAnalyticsQueryResponse(
            columns=columns,
            results=results,
            timings=response.timings,
            types=types,
            hogql="\n\n".join(part for part in hogql_parts if part) or None,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )
