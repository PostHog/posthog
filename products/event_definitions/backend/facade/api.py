"""Cross-product write helpers for event definitions."""

from typing import TYPE_CHECKING, cast

from django.apps import apps

from posthog.settings import EE_AVAILABLE

from products.event_definitions.backend.models import EventDefinition

if TYPE_CHECKING:
    from ee.models.event_definition import EnterpriseEventDefinition


def create_placeholder_event_definition(
    *, team_id: int, project_id: int, name: str, description: str | None = None
) -> None:
    """Create an event definition that ingestion can claim when the event is first seen."""
    event_definition, _ = EventDefinition.objects.get_or_create(
        team_id=team_id,
        project_id=project_id,
        name=name,
        defaults={"created_at": None, "last_seen_at": None},
    )

    if not EE_AVAILABLE:
        return

    enterprise_model = cast(type["EnterpriseEventDefinition"], apps.get_model("ee", "EnterpriseEventDefinition"))
    enterprise_event = enterprise_model.objects.filter(pk=event_definition.pk).first()
    if enterprise_event:
        if description and not getattr(enterprise_event, "description", None):
            enterprise_event.description = description
            enterprise_event.save(update_fields=["description", "updated_at"])
        return

    enterprise_event = enterprise_model(
        eventdefinition_ptr_id=event_definition.id,
        description=description or "",
    )
    enterprise_event.__dict__.update(event_definition.__dict__)
    enterprise_event.description = description or ""
    enterprise_event.save()
