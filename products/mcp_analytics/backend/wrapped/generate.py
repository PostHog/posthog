"""Compute one project's MCP Wrapped and, unless asked not to, store it as that year's snapshot."""

import dataclasses
from typing import Any

from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.mcp_analytics.backend.models import MCPAnalyticsWrapped
from products.mcp_analytics.backend.wrapped.cards import SCHEMA_VERSION, build_wrapped_cards, is_eligible
from products.mcp_analytics.backend.wrapped.queries import WrappedPeriod, fetch_monthly_calls, fetch_wrapped_aggregates


@frozen
class WrappedGeneration:
    status: MCPAnalyticsWrapped.Status
    payload: dict[str, Any]


def compute_wrapped(team: Team, year: int) -> WrappedGeneration:
    period = WrappedPeriod.for_year(team, year)
    # Timestamps only, so a project far below the bar never pays for the properties scan.
    if not is_eligible(fetch_monthly_calls(team, period)):
        return WrappedGeneration(status=MCPAnalyticsWrapped.Status.INELIGIBLE, payload={})
    cards = build_wrapped_cards(fetch_wrapped_aggregates(team, period), team.timezone)
    if cards is None:
        return WrappedGeneration(status=MCPAnalyticsWrapped.Status.INELIGIBLE, payload={})
    return WrappedGeneration(status=MCPAnalyticsWrapped.Status.READY, payload=dataclasses.asdict(cards))


def generate_wrapped_snapshot(team: Team, year: int) -> MCPAnalyticsWrapped:
    """Compute and store the snapshot. A failure is recorded and raised, and never replaces a ready snapshot."""
    try:
        generation = compute_wrapped(team, year)
    except Exception as error:
        _record_failure(team, year, error_message=str(error)[:1000])
        raise
    return _save(team, year, status=generation.status, payload=generation.payload, error_message="")


def _record_failure(team: Team, year: int, *, error_message: str) -> None:
    with team_scope(team.id):
        ready = MCPAnalyticsWrapped.objects.filter(team=team, year=year, status=MCPAnalyticsWrapped.Status.READY)
        if ready.exists():
            return
    _save(team, year, status=MCPAnalyticsWrapped.Status.FAILED, payload={}, error_message=error_message)


def _save(
    team: Team, year: int, *, status: MCPAnalyticsWrapped.Status, payload: dict[str, Any], error_message: str
) -> MCPAnalyticsWrapped:
    with team_scope(team.id):
        snapshot, _ = MCPAnalyticsWrapped.objects.update_or_create(
            team=team,
            year=year,
            defaults={
                "status": status,
                "schema_version": SCHEMA_VERSION,
                "payload": payload,
                "error_message": error_message,
                "generated_at": timezone.now(),
            },
        )
    return snapshot
