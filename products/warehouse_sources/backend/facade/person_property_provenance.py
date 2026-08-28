from collections.abc import Iterable

from posthog.models import PropertyDefinition

from products.warehouse_sources.backend.facade.hooks import WarehouseBinding

_GROUP_TARGET = "group"


def stamp_person_property_provenance(
    *,
    team_id: int,
    binding: WarehouseBinding,
    source_id: str,
    definition_id: str,
    target: str,
    group_type_index: int | None,
    property_names: Iterable[str],
    property_descriptions: dict[str, str],
) -> None:
    """Update existing person/group property definitions with their warehouse mapping provenance."""
    origin: dict[str, str] = {
        "source_id": definition_id,
        "custom_property_source_id": source_id,
        "binding_kind": binding.kind,
        "binding_id": binding.id,
    }
    # Rows stamped before materialized-view bindings existed carry this compatibility key.
    if not binding.is_saved_query:
        origin["schema_id"] = binding.id

    query = PropertyDefinition.objects.filter(team_id=team_id)
    if target == _GROUP_TARGET:
        query = query.filter(type=PropertyDefinition.Type.GROUP, group_type_index=group_type_index)
    else:
        query = query.filter(type=PropertyDefinition.Type.PERSON)

    names = list(dict.fromkeys(property_names))
    described = {name: property_descriptions[name] for name in names if property_descriptions.get(name)}
    plain = [name for name in names if name not in described]
    if plain:
        # Replacing the whole origin deliberately clears a previously configured description.
        query.filter(name__in=plain).update(warehouse_origin=origin)
    for name, description in described.items():
        query.filter(name=name).update(warehouse_origin={**origin, "description": description})
