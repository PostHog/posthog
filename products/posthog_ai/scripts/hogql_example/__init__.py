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
# runner instead of via freezegun: freezegun monkey-patches `datetime.datetime`
# process-globally, which is not thread-safe and corrupts unrelated workers
# (Temporal activities, Django request handlers) running in the same process.
# Tz-aware UTC so QueryDateRange.now_with_timezone (which calls .astimezone)
# produces output that doesn't depend on the build machine's local timezone.
FROZEN_TIME = "2025-12-10T00:00:00+00:00"
_FROZEN_DATETIME = datetime.fromisoformat(FROZEN_TIME).astimezone(UTC)


def _pin_runner_now(runner: Any, now: datetime) -> None:
    """Pin the runner's notion of "now" to a fixed datetime.

    Mutates the runner so subsequent ``to_query()`` calls resolve relative date
    ranges (``-7d``, ``-30d``, ...) against ``now`` instead of the real wall
    clock. Best-effort: runners without a standard ``query_date_range``/``context``
    surface keep their default behavior and produce non-deterministic output —
    that's strictly cosmetic since rendered skills land in a gitignored
    ``dist/`` directory.
    """
    context = getattr(runner, "context", None)
    if context is not None and hasattr(context, "now"):
        context.now = now

    query_date_range = getattr(runner, "query_date_range", None)
    if query_date_range is not None and hasattr(query_date_range, "pin_now"):
        query_date_range.pin_now(now)


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
    from posthog.hogql.filters import replace_filters
    from posthog.hogql.placeholders import replace_placeholders
    from posthog.hogql.printer.utils import to_printed_hogql

    from posthog.hogql_queries.query_runner import get_query_runner

    kind = query_dict.get("kind")

    if kind == "RecordingsQuery":
        return _render_recordings_query(query_dict, _cached_team)

    runner = get_query_runner(query_dict, _cached_team)
    _pin_runner_now(runner, _FROZEN_DATETIME)
    ast_query: ast.Expr = runner.to_query()

    from posthog.hogql_queries.ai.trace_query_runner import TraceQueryRunner

    from products.error_tracking.backend.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner
    from products.logs.backend.logs_query_runner import LogsQueryRunner

    hogql_filters = HogQLFilters()
    if isinstance(runner, ErrorTrackingQueryRunner):
        hogql_filters = runner._builder.hogql_filters()
    elif isinstance(runner, LogsQueryRunner):
        hogql_filters = HogQLFilters(dateRange=runner.query.dateRange)

    if isinstance(runner, TraceQueryRunner):
        ast_query = replace_placeholders(ast_query, {"filter_conditions": runner._get_where_clause()})

    ast_query = replace_filters(ast_query, hogql_filters, _cached_team)

    return to_printed_hogql(ast_query, _cached_team)


def _render_recordings_query(query_dict: dict[str, Any], team: Any) -> str:
    from posthog.schema import RecordingsQuery

    from posthog.hogql.printer.utils import to_printed_hogql

    from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery

    query = RecordingsQuery(**{k: v for k, v in query_dict.items() if k != "kind"})
    listing = SessionRecordingListFromQuery(team=team, query=query)
    ast_query = listing.get_query()
    return to_printed_hogql(ast_query, team)
