"""Cross-product write helpers for event definitions."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from django.apps import apps
from django.db.models import Q

from posthog.models import Team
from posthog.settings import EE_AVAILABLE

from products.event_definitions.backend.models import EventDefinition

if TYPE_CHECKING:
    from ee.models.event_definition import EnterpriseEventDefinition


@dataclass(frozen=True)
class PlaceholderEventDefinition:
    name: str
    description: str | None = None


def create_placeholder_event_definitions(*, team_id: int, definitions: Sequence[PlaceholderEventDefinition]) -> None:
    """Create event definitions that ingestion can claim when the events are first seen."""
    if not definitions:
        return

    project_id = Team.objects.values_list("project_id", flat=True).get(id=team_id)
    names = [definition.name for definition in definitions]
    event_definitions_by_name = {
        event_definition.name: event_definition
        for event_definition in EventDefinition.objects.filter(
            Q(project_id=project_id) | Q(project_id__isnull=True, team_id=project_id),
            name__in=names,
        )
    }

    for definition in definitions:
        if definition.name in event_definitions_by_name:
            continue
        event_definition, _ = EventDefinition.objects.get_or_create(
            project_id=project_id,
            name=definition.name,
            defaults={"team_id": team_id, "created_at": None, "last_seen_at": None},
        )
        event_definitions_by_name[definition.name] = event_definition

    if not EE_AVAILABLE:
        return

    enterprise_model = cast(type["EnterpriseEventDefinition"], apps.get_model("ee", "EnterpriseEventDefinition"))
    enterprise_events_by_id = enterprise_model.objects.filter(
        pk__in=[event_definition.pk for event_definition in event_definitions_by_name.values()]
    ).in_bulk()

    for definition in definitions:
        event_definition = event_definitions_by_name[definition.name]
        enterprise_event = enterprise_events_by_id.get(event_definition.pk)
        if enterprise_event:
            if definition.description and not enterprise_event.description:
                enterprise_event.description = definition.description
                enterprise_event.save(update_fields=["description", "updated_at"])
            continue

        enterprise_event = enterprise_model(
            eventdefinition_ptr_id=event_definition.id,
            description=definition.description or "",
        )
        enterprise_event.__dict__.update(event_definition.__dict__)
        enterprise_event.description = definition.description or ""
        enterprise_event.save()
