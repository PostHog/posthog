from products.event_definitions.backend.facade import api as event_definitions_api
from products.event_definitions.backend.facade.enums import PropertyType


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
    event_definitions_api.upsert_group_property_definition(
        team_id=team_id,
        project_id=project_id,
        group_type_index=group_type_index,
        name=property_name,
        property_type=detect_group_property_type(property_value),
    )
