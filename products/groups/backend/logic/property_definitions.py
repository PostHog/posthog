from posthog.models import PropertyDefinition

from products.event_definitions.backend.models import PropertyType, effective_project_id_expr, group_type_index_key_expr


def detect_group_property_type(value: object) -> PropertyType:
    if value is None:
        return PropertyType.String
    elif isinstance(value, bool):
        return PropertyType.Boolean
    elif isinstance(value, int | float):
        return PropertyType.Numeric
    elif isinstance(value, str):
        if value.lower() in ("true", "false"):
            return PropertyType.Boolean
        return PropertyType.String
    return PropertyType.String


def create_property_definition(
    team_id: int, project_id: int, group_type_index: int, property_name: str, property_value: object
) -> None:
    """Create or update PostgreSQL PropertyDefinition for group property"""
    property_type = detect_group_property_type(property_value)
    is_numerical = property_type == PropertyType.Numeric

    # Match on the key of posthog_propdef_proj_uniq. Then the lookup is a single index seek, and it finds a
    # definition that another environment of the project created, so the insert cannot violate that constraint.
    PropertyDefinition.objects.alias(
        effective_project_id=effective_project_id_expr(),
        group_type_index_key=group_type_index_key_expr(),
    ).filter(effective_project_id=project_id, group_type_index_key=group_type_index).update_or_create(
        name=property_name,
        type=PropertyDefinition.Type.GROUP,
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
