"""Find the most common paths that sessions take before and after a click on one element.

Two queries run against `events`:

- The stats query counts every matching click and session, so a caller can tell an element that
  nobody clicks from an element whose clicks follow no common path.
- The paths query takes the sessions with a matching click, capped at `MAX_ANALYZED_SESSIONS`, and
  reads the pageviews and autocaptured events around the first matching click of each session.
"""

import re
import copy
from datetime import datetime, timedelta
from typing import Any

from posthog.schema import DateRange

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import apply_path_cleaning, property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team

from ..facade.contracts import (
    MAX_ELEMENT_PATHS_RANGE_DAYS,
    MAX_SELECTOR_LENGTH,
    MAX_TEXT_LENGTH,
    MAX_URL_LENGTH,
    ElementClickStep,
    ElementPath,
    ElementPathNode,
    ElementPathsQuery,
    ElementPathsQueryError,
    ElementPathsResult,
    PageviewStep,
)
from ..facade.enums import UrlMatching
from .funnels import step_to_events_node

# Sessions are picked by the hash of their ID, so the cap is an unbiased sample of the anchor sessions.
MAX_ANALYZED_SESSIONS = 10_000
# Raw events kept on each side of the anchor before consecutive duplicates collapse. This is larger
# than the step limit so that repeated pageviews and clicks still leave enough distinct nodes.
RAW_EVENTS_PER_SIDE = 25
# A path that one session took is not a common path.
MIN_SESSIONS_PER_PATH = 2

_ANCHOR_KIND = "anchor"
_PAGEVIEW_KIND = "pageview"
_CLICK_KIND = "click"
_URL_PREFIX_REGEX = "^(?:[a-zA-Z][a-zA-Z0-9+.-]*://[^/?#]*)?"
_URL_SUFFIX_REGEX = "/*(?:[?#].*)?$"
_ALIAS_REGEX = "[^?#]*"
_CSS_ID = re.compile(r"^-?[A-Za-z_][A-Za-z0-9_-]*$")
_NODE_FIELDS = ("kind", "path", "tag", "element_id", "text", "href")


@frozen
class NodeKey:
    """One node as the paths query returns it. Unused fields are empty strings."""

    kind: str
    path: str
    tag: str
    element_id: str
    text: str
    href: str


@frozen
class PathCleaning:
    aliases: tuple[str, ...]

    @property
    def has_empty_alias(self) -> bool:
        return any(not alias for alias in self.aliases)


def _pageview_node(path: str, cleaning: PathCleaning) -> ElementPathNode:
    trimmed = path.rstrip("/")
    escaped = re.escape(trimmed)
    replaced = False
    for alias in sorted({a for a in cleaning.aliases if a}, key=len, reverse=True):
        escaped_alias = re.escape(alias)
        if escaped_alias in escaped:
            escaped = escaped.replace(escaped_alias, _ALIAS_REGEX)
            replaced = True
    url = f"{_URL_PREFIX_REGEX}{escaped}{_URL_SUFFIX_REGEX}"
    # A rule with an empty alias deletes part of the path without a marker, so no regex built from
    # the cleaned path can promise to match the raw URLs.
    exact = not replaced and not cleaning.has_empty_alias
    if len(url) > MAX_URL_LENGTH:
        return ElementPathNode(
            label=path,
            is_anchor=False,
            step=PageviewStep(url=trimmed[:MAX_URL_LENGTH] or "/", url_matching=UrlMatching.CONTAINS),
            step_is_exact=False,
        )
    return ElementPathNode(
        label=path, is_anchor=False, step=PageviewStep(url=url, url_matching=UrlMatching.REGEX), step_is_exact=exact
    )


def _click_node(key: NodeKey) -> ElementPathNode:
    if key.element_id and _CSS_ID.match(key.element_id):
        selector = f"#{key.element_id}"
    else:
        selector = key.tag or "*"
    text = key.text if 0 < len(key.text) <= MAX_TEXT_LENGTH else None
    href = key.href if 0 < len(key.href) <= MAX_URL_LENGTH else None
    label = key.text or key.href or (f"{key.tag}#{key.element_id}" if key.element_id else key.tag) or "element"
    return ElementPathNode(
        label=label[:MAX_TEXT_LENGTH],
        is_anchor=False,
        step=ElementClickStep(selector=selector[:MAX_SELECTOR_LENGTH], text=text, href=href),
        # The selector names only the innermost tag or id, so it can match other elements too.
        step_is_exact=False,
    )


def anchor_label(anchor: ElementClickStep) -> str:
    return (anchor.text or anchor.href or anchor.selector)[:MAX_TEXT_LENGTH]


def node_from_key(key: NodeKey, anchor: ElementClickStep, cleaning: PathCleaning) -> ElementPathNode:
    if key.kind == _ANCHOR_KIND:
        return ElementPathNode(label=anchor_label(anchor), is_anchor=True, step=anchor, step_is_exact=True)
    if key.kind == _PAGEVIEW_KIND:
        return _pageview_node(key.path, cleaning)
    return _click_node(key)


def path_from_row(
    row: tuple[Any, ...], anchor: ElementClickStep, cleaning: PathCleaning, analyzed_session_count: int
) -> ElementPath:
    raw_nodes, anchor_index, session_count = row
    nodes = [node_from_key(NodeKey(**dict(zip(_NODE_FIELDS, raw))), anchor, cleaning) for raw in raw_nodes]
    return ElementPath(
        session_count=int(session_count),
        share_of_anchor_sessions=int(session_count) / analyzed_session_count if analyzed_session_count else 0.0,
        anchor_index=int(anchor_index),
        nodes=nodes,
    )


@frozen
class ResolvedRange:
    date_from: datetime
    date_to: datetime


def resolve_date_range(team: Team, query: ElementPathsQuery, now: datetime) -> ResolvedRange:
    date_range = QueryDateRange(
        date_range=DateRange(date_from=query.date_from, date_to=query.date_to),
        team=team,
        interval=None,
        now=now,
    )
    resolved = ResolvedRange(date_from=date_range.date_from(), date_to=date_range.date_to())
    if resolved.date_from >= resolved.date_to:
        raise ElementPathsQueryError("The start date must be before the end date.")
    if resolved.date_to - resolved.date_from > timedelta(days=MAX_ELEMENT_PATHS_RANGE_DAYS):
        raise ElementPathsQueryError(f"The date range can be at most {MAX_ELEMENT_PATHS_RANGE_DAYS} days.")
    return resolved


@frozen
class ElementPathsQueries:
    stats: ast.SelectQuery
    paths: ast.SelectQuery


def _anchor_expr(team: Team, anchor: ElementClickStep) -> ast.Expr:
    node = step_to_events_node(anchor)
    return ast.And(
        exprs=[
            parse_expr("event = {event}", {"event": ast.Constant(value=node.event)}),
            property_to_expr(node.properties or [], team),
        ]
    )


def _base_filters(team: Team, query: ElementPathsQuery, date_range: ResolvedRange) -> ast.Expr:
    filters: list[ast.Expr] = [
        parse_expr(
            "timestamp >= {date_from} AND timestamp <= {date_to}",
            {"date_from": ast.Constant(value=date_range.date_from), "date_to": ast.Constant(value=date_range.date_to)},
        ),
        _anchor_expr(team, query.anchor),
    ]
    if query.filter_test_accounts and team.test_account_filters:
        filters.append(property_to_expr(team.test_account_filters, team))
    return ast.And(exprs=filters)


def _page_path_expr(team: Team) -> ast.Expr:
    raw_path = parse_expr(
        "replaceRegexpOne(path(ifNull(properties.$current_url, '')), {trailing}, {keep})",
        {"trailing": ast.Constant(value="(.)/+$"), "keep": ast.Constant(value="\\1")},
    )
    normalized = parse_expr("if(empty({p}), '/', {p})", {"p": raw_path})
    return apply_path_cleaning(normalized, team)


def build_queries(team: Team, query: ElementPathsQuery, date_range: ResolvedRange) -> ElementPathsQueries:
    base_filters = _base_filters(team, query, date_range)

    stats = parse_select(
        """
        SELECT count() AS clicks, uniqExactIf($session_id, $session_id != '') AS sessions
        FROM events
        WHERE {filters}
        """,
        {"filters": base_filters},
    )

    anchor_sessions = parse_select(
        """
        SELECT $session_id AS session_id, min(timestamp) AS anchor_timestamp
        FROM events
        WHERE {filters} AND $session_id != ''
        GROUP BY session_id
        ORDER BY cityHash64(session_id)
        LIMIT {max_sessions}
        """,
        {"filters": copy.deepcopy(base_filters), "max_sessions": ast.Constant(value=MAX_ANALYZED_SESSIONS)},
    )

    anchor_node = parse_expr("tuple({kind}, '', '', '', '', '')", {"kind": ast.Constant(value=_ANCHOR_KIND)})
    node = parse_expr(
        """
        multiIf(
            {is_anchor}, {anchor_node},
            event = '$pageview', tuple({pageview}, {page_path}, '', '', '', ''),
            tuple(
                {click},
                '',
                extract(elements_chain, '^([A-Za-z][A-Za-z0-9_-]*)'),
                extract(elements_chain, '^[^;]*?[:"]attr_id="([^"]*)"'),
                arrayElement(elements_chain_texts, 1),
                elements_chain_href
            )
        )
        """,
        {
            "is_anchor": _anchor_expr(team, query.anchor),
            "anchor_node": copy.deepcopy(anchor_node),
            "pageview": ast.Constant(value=_PAGEVIEW_KIND),
            "page_path": _page_path_expr(team),
            "click": ast.Constant(value=_CLICK_KIND),
        },
    )

    paths = parse_select(
        """
        SELECT nodes, anchor_index, count() AS session_count
        FROM (
            SELECT
                arraySlice(arrayCompact(arrayMap(x -> tupleElement(x, 2), before_raw)), 1, {steps_before}) AS before_newest_first,
                arraySlice(
                    arrayCompact(arrayConcat([{anchor_node}], arrayMap(x -> tupleElement(x, 2), after_raw))),
                    2,
                    {steps_after}
                ) AS after_nodes,
                arrayConcat(arrayReverse(before_newest_first), [{anchor_node}], after_nodes) AS nodes,
                length(before_newest_first) AS anchor_index
            FROM (
                SELECT
                    events.$session_id AS session_id,
                    groupArraySortedIf({raw_cap})(
                        tuple(negate(toUnixTimestamp64Milli(events.timestamp)), {node}),
                        events.timestamp < anchors.anchor_timestamp
                    ) AS before_raw,
                    groupArraySortedIf({raw_cap})(
                        tuple(toUnixTimestamp64Milli(events.timestamp), {node}),
                        events.timestamp > anchors.anchor_timestamp
                    ) AS after_raw
                FROM events
                INNER JOIN ({anchor_sessions}) AS anchors ON events.$session_id = anchors.session_id
                WHERE events.event IN ('$pageview', '$autocapture')
                    AND events.timestamp >= {date_from}
                    AND events.timestamp <= {date_to}
                    AND events.$session_id IN (SELECT session_id FROM ({anchor_sessions_filter}))
                GROUP BY session_id
            )
        )
        WHERE length(nodes) > 1
        GROUP BY nodes, anchor_index
        HAVING session_count >= {min_sessions}
        ORDER BY session_count DESC, nodes ASC
        LIMIT {limit}
        """,
        {
            "steps_before": ast.Constant(value=query.steps_before),
            "steps_after": ast.Constant(value=query.steps_after),
            "anchor_node": anchor_node,
            "raw_cap": ast.Constant(value=RAW_EVENTS_PER_SIDE),
            "node": node,
            "anchor_sessions": anchor_sessions,
            "anchor_sessions_filter": copy.deepcopy(anchor_sessions),
            "date_from": ast.Constant(value=date_range.date_from),
            "date_to": ast.Constant(value=date_range.date_to),
            "min_sessions": ast.Constant(value=MIN_SESSIONS_PER_PATH),
            "limit": ast.Constant(value=query.limit),
        },
    )
    assert isinstance(stats, ast.SelectQuery) and isinstance(paths, ast.SelectQuery)
    return ElementPathsQueries(stats=stats, paths=paths)


def _execute(query: ast.SelectQuery, team: Team, query_type: str) -> list[Any]:
    return execute_hogql_query(
        query=query,
        team=team,
        query_type=query_type,
        # The toolbar shows the result while the person waits.
        workload=Workload.ONLINE,
        limit_context=LimitContext.QUERY,
    ).results


def get_element_paths(team_id: int, query: ElementPathsQuery, now: datetime) -> ElementPathsResult:
    team = Team.objects.get(id=team_id)
    date_range = resolve_date_range(team, query, now)
    queries = build_queries(team, query, date_range)

    [(click_count, session_count)] = _execute(queries.stats, team, "user_journeys_element_paths_stats")
    analyzed_session_count = min(int(session_count), MAX_ANALYZED_SESSIONS)
    paths: list[ElementPath] = []
    if analyzed_session_count >= MIN_SESSIONS_PER_PATH:
        cleaning = PathCleaning(aliases=tuple(rule.alias or "" for rule in team.path_cleaning_filter_models()))
        rows = _execute(queries.paths, team, "user_journeys_element_paths")
        paths = [path_from_row(row, query.anchor, cleaning, analyzed_session_count) for row in rows]

    return ElementPathsResult(
        date_from=date_range.date_from,
        date_to=date_range.date_to,
        anchor_click_count=int(click_count),
        anchor_session_count=int(session_count),
        analyzed_session_count=analyzed_session_count,
        paths=paths,
    )
