from dataclasses import fields
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter

from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from ..facade.contracts import CreateJourneyInput, JourneyNotFoundError, JourneyStep, UpdateJourneyInput
from ..models import Journey

_STEPS_ADAPTER: TypeAdapter[list[JourneyStep]] = TypeAdapter(list[JourneyStep])


def steps_to_json(steps: list[JourneyStep]) -> list[dict[str, Any]]:
    return _STEPS_ADAPTER.dump_python(steps, mode="json")


def get_journey(team_id: int, journey_id: UUID) -> Journey:
    try:
        return Journey.objects.for_team(team_id).get(id=journey_id)
    except Journey.DoesNotExist as e:
        raise JourneyNotFoundError(f"Journey {journey_id} not found") from e


def list_journeys(team_id: int, page: PageRequest) -> Page[Journey]:
    return select_page(Journey.objects.for_team(team_id).order_by("-created_at"), page)


def create_journey(team_id: int, created_by_id: int | None, data: CreateJourneyInput) -> Journey:
    return Journey.objects.for_team(team_id).create(
        team_id=team_id,
        created_by_id=created_by_id,
        name=data.name,
        description=data.description,
        steps=steps_to_json(data.steps),
        conversion_window_minutes=data.conversion_window_minutes,
        source=data.source,
    )


def update_journey(team_id: int, journey_id: UUID, data: UpdateJourneyInput) -> Journey:
    journey = get_journey(team_id, journey_id)
    changes = {f.name: getattr(data, f.name) for f in fields(data) if getattr(data, f.name) is not None}
    if "steps" in changes:
        changes["steps"] = steps_to_json(changes["steps"])
    for field, value in changes.items():
        setattr(journey, field, value)
    if changes:
        journey.save(update_fields=[*changes, "updated_at"])
    return journey


def delete_journey(team_id: int, journey_id: UUID) -> None:
    get_journey(team_id, journey_id).delete()
