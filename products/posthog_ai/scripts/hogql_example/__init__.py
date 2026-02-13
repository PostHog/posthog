"""HogQL example renderer for skill templates.

Provides a function to render a query dict (with a `kind` field) into
the corresponding HogQL string via the query runner infrastructure.

Only available when DEBUG=True, since it requires Django and a database.
"""

from __future__ import annotations

from typing import Any

_cached_team: Any = None

FROZEN_TIME = "2025-12-10T00:00:00"


def render_hogql_example(query_dict: dict[str, Any]) -> str:
    """Render a query dict to a HogQL string using the query runner pipeline.

    Time is frozen to FROZEN_TIME so that relative date ranges produce
    deterministic output regardless of when the build runs.

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

    from freezegun import freeze_time

    from posthog.schema import HogQLFilters

    from posthog.hogql.filters import replace_filters
    from posthog.hogql.printer.utils import to_printed_hogql

    from posthog.hogql_queries.query_runner import get_query_runner

    with freeze_time(FROZEN_TIME):
        runner = get_query_runner(query_dict, _cached_team)
        ast_query = runner.to_query()

        from products.error_tracking.backend.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner
        from products.logs.backend.logs_query_runner import LogsQueryRunner

        hogql_filters = HogQLFilters()
        if isinstance(runner, ErrorTrackingQueryRunner):
            hogql_filters = HogQLFilters(
                filterTestAccounts=runner.query.filterTestAccounts,
                properties=runner.hogql_properties,
            )
        elif isinstance(runner, LogsQueryRunner):
            hogql_filters = HogQLFilters(dateRange=runner.query.dateRange)
        ast_query = replace_filters(ast_query, hogql_filters, _cached_team)

        return to_printed_hogql(ast_query, _cached_team)
