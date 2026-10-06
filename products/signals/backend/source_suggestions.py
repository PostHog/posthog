"""Which products a report may suggest the team turn on, and the suggestion a report shows.

A report suggests a product only while the team does not use it. The checks here decide that, and
each one stays cheap enough to run on a report read: team opt-in fields first, then event
definitions seen in the stale window, and for logs a one-row ClickHouse probe behind a cache.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from django.core.cache import cache
from django.utils import timezone

import structlog
from pydantic import ValidationError

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import EventDefinition, Team
from posthog.taxonomy.taxonomy import STALE_EVENT_DAYS

from products.signals.backend.artefact_schemas import SourceSuggestion
from products.signals.backend.enums import SuggestedSourceProduct
from products.signals.backend.models import SignalReportArtefact

logger = structlog.get_logger(__name__)

ERROR_TRACKING_EVENTS = ("$exception",)
LLM_ANALYTICS_EVENTS = ("$ai_generation", "$ai_trace")

# A team that starts sending logs keeps them, so a positive answer is cached for a long time. A
# negative answer expires sooner, so a suggestion to turn logs on stops showing soon after the
# first logs arrive.
HAS_LOGS_TRUE_TTL = int(dt.timedelta(days=1).total_seconds())
HAS_LOGS_FALSE_TTL = int(dt.timedelta(minutes=10).total_seconds())


def _has_recent_event(team: Team, event_names: tuple[str, ...]) -> bool:
    return EventDefinition.objects.filter(
        team_id=team.id,
        name__in=event_names,
        last_seen_at__gte=timezone.now() - dt.timedelta(days=STALE_EVENT_DAYS),
    ).exists()


def _has_logs(team: Team) -> bool:
    # products.logs depends on products.signals, so signals runs its own probe instead of
    # importing the logs product's helper.
    cache_key = f"signals:source_suggestions:team:{team.id}:has_logs"
    cached = cache.get(cache_key)
    if cached is not None:
        return bool(cached)
    query = parse_select("SELECT 1 FROM logs LIMIT 1")
    assert isinstance(query, ast.SelectQuery)
    response = execute_hogql_query(
        query_type="SignalsSourceSuggestionHasLogsQuery", query=query, team=team, workload=Workload.LOGS
    )
    has_logs = bool(response.results)
    cache.set(cache_key, has_logs, HAS_LOGS_TRUE_TTL if has_logs else HAS_LOGS_FALSE_TTL)
    return has_logs


def _uses_error_tracking(team: Team) -> bool:
    # Server SDKs capture exceptions without the autocapture opt-in, so recent exception events
    # also count as in use.
    return bool(team.autocapture_exceptions_opt_in) or _has_recent_event(team, ERROR_TRACKING_EVENTS)


_IN_USE_CHECKS: dict[SuggestedSourceProduct, Callable[[Team], bool]] = {
    SuggestedSourceProduct.SESSION_REPLAY: lambda team: bool(team.session_recording_opt_in),
    SuggestedSourceProduct.ERROR_TRACKING: _uses_error_tracking,
    SuggestedSourceProduct.LLM_ANALYTICS: lambda team: _has_recent_event(team, LLM_ANALYTICS_EVENTS),
    SuggestedSourceProduct.LOGS: _has_logs,
}


def is_product_in_use(team: Team, product: SuggestedSourceProduct) -> bool:
    return _IN_USE_CHECKS[product](team)


def unused_suggestable_products(team: Team) -> list[SuggestedSourceProduct]:
    return [product for product in SuggestedSourceProduct if not is_product_in_use(team, product)]


def current_source_suggestion(team: Team, report_id: str) -> SourceSuggestion | None:
    """The report's latest suggestion, or None when it has none or the team now uses the product."""
    artefact = (
        SignalReportArtefact.objects.filter(
            team_id=team.id, report_id=report_id, type=SignalReportArtefact.ArtefactType.SOURCE_SUGGESTION
        )
        .order_by("-created_at")
        .only("id", "content")
        .first()
    )
    if artefact is None:
        return None
    try:
        suggestion = SourceSuggestion.model_validate_json(artefact.content)
    except ValidationError:
        logger.warning("signals.source_suggestion.invalid_content", report_id=report_id, artefact_id=str(artefact.id))
        return None
    if is_product_in_use(team, suggestion.product):
        return None
    return suggestion
