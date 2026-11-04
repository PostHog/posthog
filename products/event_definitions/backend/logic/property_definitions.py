"""Property definition reads and writes that callers outside the product need."""

from products.event_definitions.backend.facade.enums import PropertyDefinitionType, PropertyType
from products.event_definitions.backend.models.property_definition import (
    PropertyDefinition,
    effective_project_id_expr,
    group_type_index_key_expr,
)


def upsert_group_property_definition(
    *, team_id: int, project_id: int, group_type_index: int, name: str, property_type: PropertyType
) -> None:
    is_numerical = property_type == PropertyType.Numeric
    # Match on the key of posthog_propdef_proj_uniq. Then the lookup is a single index seek, and it finds a
    # definition that another environment of the project created, so the insert cannot violate that constraint.
    PropertyDefinition.objects.alias(
        effective_project_id=effective_project_id_expr(),
        group_type_index_key=group_type_index_key_expr(),
    ).filter(effective_project_id=project_id, group_type_index_key=group_type_index).update_or_create(
        name=name,
        type=PropertyDefinitionType.GROUP,
        defaults={
            "property_type": property_type.value,
            "is_numerical": is_numerical,
        },
        create_defaults={
            "team_id": team_id,
            "project_id": project_id,
            "group_type_index": group_type_index,
            "property_type": property_type.value,
            "is_numerical": is_numerical,
        },
    )


def get_property_type(
    *, project_id: int, name: str, type: PropertyDefinitionType, group_type_index: int | None
) -> PropertyType | None:
    try:
        property_type = (
            PropertyDefinition.objects.alias(effective_project_id=effective_project_id_expr())
            .values_list("property_type", flat=True)
            .get(
                effective_project_id=project_id,
                name=name,
                type=type,
                # Only group definitions carry a group type index.
                group_type_index=group_type_index if type == PropertyDefinitionType.GROUP else None,
            )
        )
    except PropertyDefinition.DoesNotExist:
        return None
    return PropertyType(property_type) if property_type else None
