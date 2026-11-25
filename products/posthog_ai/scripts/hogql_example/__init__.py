"""HogQL example renderer for skill templates.

Provides a function to render a query dict (with a `kind` field) into
the corresponding HogQL string via the query runner infrastructure.

Only available when DEBUG=True, since it requires Django and a database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_cached_team: Any = None

# Used as the synthetic "now" for relative date ranges (e.g. "-7d") so the
# rendered HogQL is reproducible and doesn't drift between builds. Pinned per
# runner instead of via a clock mock: clock mocks are process-global, so they hand
# unrelated workers in the same process the wrong time.
# Tz-aware UTC so QueryDateRange.now_with_timezone (which calls .astimezone)
# produces output that doesn't depend on the build machine's local timezone.
FROZEN_TIME = "2025-12-10T00:00:00+00:00"
_FROZEN_DATETIME = datetime.fromisoformat(FROZEN_TIME).astimezone(UTC)


def _pin_runner_now(runner: Any, now: datetime) -> None:
    """Pin the runner's notion of "now" to a fixed datetime.

    Mutates the runner so subsequent ``to_query()`` calls resolve relative date
    ranges (``-7d``, ``-30d``, ...) against ``now`` instead of the real wall
    clock. Runners without a standard ``query_date_range``/``context`` surface keep
    reading the wall clock, so their kinds need ``_resolve_relative_bounds`` too.
    Output that changes between builds is not cosmetic: the Modal eval sandbox
    image copies the rendered skills, so any changed byte rebuilds the image.
    """
    context = getattr(runner, "context", None)
    if context is not None and hasattr(context, "now"):
        context.now = now

    query_date_range = getattr(runner, "query_date_range", None)
    if query_date_range is not None and hasattr(query_date_range, "pin_now"):
        query_date_range.pin_now(now)


def _absolute_date(value: str | None, now: datetime, timezone_info: Any, **parse_options: bool) -> str | None:
    if value is None or value == "all":
        return value
    from posthog.utils import relative_date_parse

    return relative_date_parse(value, timezone_info, now=now, **parse_options).isoformat()


def _resolve_relative_bounds(query_dict: dict[str, Any], now: datetime, timezone_info: Any) -> dict[str, Any]:
    """Resolve relative bounds against ``now`` for the kinds whose runners read the wall clock while
    they are constructed, before ``_pin_runner_now`` can reach them. The parse options and defaults
    copy the runners, so the printed query keeps the shape a real request produces."""
    kind = query_dict.get("kind")
    if kind == "ErrorTrackingQuery":
        date_range = dict(query_dict.get("dateRange") or {})
        date_range["date_from"] = _absolute_date(date_range.get("date_from"), now, timezone_info, always_truncate=True)
        date_range["date_to"] = (
            _absolute_date(date_range.get("date_to"), now, timezone_info, increase=True) or now.isoformat()
        )
        return {**query_dict, "dateRange": date_range}
    if kind == "SessionsQuery":
        before = query_dict.get("before")
        after = query_dict.get("after") or (None if before else "-1h")
        return {
            **query_dict,
            "after": _absolute_date(after, now, timezone_info),
            "before": _absolute_date(before, now, timezone_info) or now.isoformat(),
        }
    return query_dict


def render_hogql_example(query_dict: dict[str, Any]) -> str:
    """Render a query dict to a HogQL string using the query runner pipeline.

    Relative date ranges are resolved against ``FROZEN_TIME`` so output is
    reproducible across builds.

    Usage in a template::

        {{ render_hogql_example({"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}], "dateRange": {"date_from": "-7d"}}) }}

    Raises:
        RuntimeError: If DEBUG is not True or no Team exists in the database.
    """
    from django.conf import settings

    if not settings.DEBUG:
        raise RuntimeError("render_hogql_example is only available when DEBUG=True")

    global _cached_team
    if _cached_team is None:
        from posthog.models.team import Team

        _cached_team = Team.objects.first()
        if _cached_team is None:
            raise RuntimeError("render_hogql_example requires at least one Team in the database")

    from posthog.schema import HogQLFilters

    from posthog.hogql import ast
    from posthog.hogql.database.database import Database
    from posthog.hogql.filters import ReplaceFilters
    from posthog.hogql.placeholders import replace_placeholders
    from posthog.hogql.printer.utils import to_printed_hogql

    from posthog.hogql_queries.query_runner import get_query_runner

    kind = query_dict.get("kind")

    if kind == "RecordingsQuery":
        return _render_recordings_query(query_dict, _cached_team)

    query_dict = _resolve_relative_bounds(query_dict, _FROZEN_DATETIME, _cached_team.timezone_info)
    runner = get_query_runner(query_dict, _cached_team)
    _pin_runner_now(runner, _FROZEN_DATETIME)
    ast_query: ast.Expr = runner.to_query()

    from posthog.hogql_queries.ai.trace_query_runner import TraceQueryRunner

    from products.error_tracking.backend.facade.queries import ErrorTrackingQueryRunner
    from products.logs.backend.facade.queries import LogsQueryRunner

    hogql_filters = HogQLFilters()
    if isinstance(runner, ErrorTrackingQueryRunner):
        hogql_filters = runner._builder.hogql_filters()
    elif isinstance(runner, LogsQueryRunner):
        hogql_filters = HogQLFilters(dateRange=runner.query.dateRange)

    if isinstance(runner, TraceQueryRunner):
        ast_query = replace_placeholders(ast_query, {"filter_conditions": runner._get_where_clause()})

    # replace_filters resolves a relative dateRange against the wall clock and takes no "now",
    # so the visitor is built here to pin the instant it resolves against.
    filters_visitor = ReplaceFilters(hogql_filters, _cached_team, Database.create_for(team=_cached_team))
    filters_visitor._now = _FROZEN_DATETIME
    ast_query = filters_visitor.visit(ast_query)

    return to_printed_hogql(ast_query, _cached_team)


def _render_recordings_query(query_dict: dict[str, Any], team: Any) -> str:
    from posthog.schema import RecordingsQuery

    from posthog.hogql.printer.utils import to_printed_hogql

    from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery

    query = RecordingsQuery(**{k: v for k, v in query_dict.items() if k != "kind"})
    listing = SessionRecordingListFromQuery(team=team, query=query, now=_FROZEN_DATETIME)
    ast_query = listing.get_query()
    return to_printed_hogql(ast_query, team)
