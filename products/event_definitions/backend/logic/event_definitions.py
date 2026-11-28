"""Event definition reads that callers outside the product need."""

from collections.abc import Sequence
from uuid import UUID

from django.db.models.functions import Substr

from products.event_definitions.backend.facade.contracts import EventMetadataSummary
from products.event_definitions.backend.models.event_definition import EventDefinition
from products.event_definitions.backend.models.property_definition import effective_project_id_expr


def get_event_descriptions(*, project_id: int, names: Sequence[str]) -> dict[str, str]:
    rows = (
        EventDefinition.objects.alias(effective_project_id=effective_project_id_expr())
        .filter(effective_project_id=project_id, name__in=names)
        .exclude(metadata__description__isnull=True)
        .exclude(metadata__description="")
        .values_list("name", "metadata__description")
    )
    return {name: description for name, description in rows if description}


def get_event_metadata_summaries(
    *, project_id: int, definition_ids: Sequence[UUID], description_length: int, using: str
) -> list[EventMetadataSummary]:
    rows = (
        EventDefinition.objects.using(using)
        .alias(effective_project_id=effective_project_id_expr())
        .filter(effective_project_id=project_id, pk__in=definition_ids, metadata__isnull=False)
        .annotate(short_description=Substr("metadata__description", 1, description_length))
        .values_list("name", "short_description", "metadata__hidden")
    )
    return [
        EventMetadataSummary(name=name, description=description or "", hidden=bool(hidden))
        for name, description, hidden in rows
    ]
