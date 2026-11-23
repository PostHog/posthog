"""Compute one project's MCP Wrapped and, unless asked not to, store it as that year's snapshot."""

import dataclasses
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.models.utils import strip_null_bytes

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
    # Tool and server names come from event properties, and a NUL in one makes Postgres reject the whole payload.
    return WrappedGeneration(
        status=MCPAnalyticsWrapped.Status.READY, payload=strip_null_bytes(dataclasses.asdict(cards))
    )


def generate_wrapped_snapshot(team: Team, year: int) -> MCPAnalyticsWrapped:
    """Compute and store the snapshot. A failure is recorded and raised, and never replaces a ready snapshot."""
    if team.parent_team_id is not None:
        # Rows are keyed by the parent project, so a child environment's wrap would overwrite its parent's.
        raise ValueError(f"Team {team.id} is an environment of team {team.parent_team_id}. Generate the parent's wrap.")
    try:
        generation = compute_wrapped(team, year)
        return _save(team, year, status=generation.status, payload=generation.payload, error_message="")
    except Exception as error:
        _record_failure(team, year, error_message=str(error)[:1000])
        raise


def _record_failure(team: Team, year: int, *, error_message: str) -> None:
    failure = {
        "status": MCPAnalyticsWrapped.Status.FAILED,
        "schema_version": SCHEMA_VERSION,
        "payload": {},
        "error_message": error_message,
        "generated_at": timezone.now(),
    }
    with team_scope(team.id):
        # Each write is one conditional statement, so a run that saves READY at the same time is never overwritten.
        not_ready = MCPAnalyticsWrapped.objects.filter(team=team, year=year).exclude(
            status=MCPAnalyticsWrapped.Status.READY
        )
        if not_ready.update(**failure):
            return
        try:
            with transaction.atomic():
                MCPAnalyticsWrapped.objects.create(team=team, year=year, **failure)
        except IntegrityError:
            not_ready.update(**failure)


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
