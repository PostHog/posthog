"""
Facade for user_journeys.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from posthog.schema import FunnelsQuery

from posthog.paging import Page, PageRequest

from ..feature_flags import is_user_journeys_enabled
from ..logic import element_paths, funnels, journeys
from ..models import Journey as JourneyModel
from . import contracts
from .enums import JourneySource


def is_enabled(team_id: int) -> bool:
    return is_user_journeys_enabled(team_id)


def _to_contract(journey: JourneyModel) -> contracts.Journey:
    return contracts.Journey(
        id=journey.id,
        team_id=journey.team_id,
        name=journey.name,
        description=journey.description,
        # The pydantic contract parses the stored JSON into typed steps, so a malformed row fails here.
        steps=journey.steps,
        conversion_window_minutes=journey.conversion_window_minutes,
        source=JourneySource(journey.source),
        created_by_id=journey.created_by_id,
        created_at=journey.created_at,
        updated_at=journey.updated_at,
    )


def list_journeys(team_id: int, page: PageRequest) -> Page[contracts.Journey]:
    """One page of the team's journeys, newest first, and the total count, paged in SQL."""
    return journeys.list_journeys(team_id, page).map(_to_contract)


def get_journey(team_id: int, journey_id: UUID) -> contracts.Journey:
    return _to_contract(journeys.get_journey(team_id, journey_id))


def create_journey(team_id: int, created_by_id: int | None, data: contracts.CreateJourneyInput) -> contracts.Journey:
    return _to_contract(journeys.create_journey(team_id, created_by_id, data))


def update_journey(team_id: int, journey_id: UUID, data: contracts.UpdateJourneyInput) -> contracts.Journey:
    return _to_contract(journeys.update_journey(team_id, journey_id, data))


def delete_journey(team_id: int, journey_id: UUID) -> None:
    journeys.delete_journey(team_id, journey_id)


def journey_to_funnels_query(journey: contracts.Journey) -> FunnelsQuery:
    """The ordered, per-session funnel that measures conversion through the journey's steps."""
    return funnels.journey_to_funnels_query(journey)


def get_element_paths(team_id: int, query: contracts.ElementPathsQuery) -> contracts.ElementPathsResult:
    """The most common paths that sessions take before and after a click on one element."""
    return element_paths.get_element_paths(team_id, query, now=datetime.now(UTC))
