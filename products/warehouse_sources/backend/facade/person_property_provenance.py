"""Writes the warehouse mapping provenance carried on person and group property definitions.

Owned here so both writers share one implementation: the post-sync pipeline stamps it after a run,
and a mapping/description update from the API stamps it without waiting for the next value change.
"""

from collections.abc import Iterable

from django.db.models import Q

from posthog.models import PropertyDefinition

from products.warehouse_sources.backend.facade.hooks import WarehouseBinding

_GROUP_TARGET = "group"

# Keep this in lockstep with property-defs-rs: it admits property names up to half Django's
# CharField limit, measured as UTF-8 bytes, and sanitizes NULs immediately before persistence.
MAX_PROPERTY_NAME_BYTES = 200


def stamp_person_property_provenance(
    *,
    team_id: int,
    project_id: int,
    binding: WarehouseBinding,
    source_id: str,
    definition_id: str,
    target: str,
    group_type_index: int | None,
    property_names: Iterable[str],
    property_descriptions: dict[str, str],
) -> None:
    """Record which warehouse source owns each mapped person/group property definition."""
    origin: dict[str, str] = {
        "source_id": definition_id,
        "custom_property_source_id": source_id,
        "binding_kind": binding.kind,
        "binding_id": binding.id,
    }
    # Kept for schema bindings: rows stamped before views were supported carry this key, so dropping
    # it would leave two stamps of the same schema describing it differently.
    if not binding.is_saved_query:
        origin["schema_id"] = binding.id

    canonical_descriptions: dict[str, str] = {}
    for name in property_names:
        if len(name.encode()) > MAX_PROPERTY_NAME_BYTES:
            continue
        canonical_name = name.replace("\x00", "\ufffd")
        canonical_descriptions.setdefault(canonical_name, property_descriptions.get(name, ""))

    if not canonical_descriptions:
        return

    names = list(canonical_descriptions)
    definition_type = PropertyDefinition.Type.PERSON
    definition_group_type_index = None
    if target == _GROUP_TARGET:
        if group_type_index is None:
            return
        definition_type = PropertyDefinition.Type.GROUP
        definition_group_type_index = group_type_index

    # Property definitions are unique and read by effective project. Include legacy rows whose
    # project_id is null so the conflict-safe insert and the final stamp address the same identity.
    query = PropertyDefinition.objects.filter(Q(project_id=project_id) | Q(project_id__isnull=True, team_id=project_id))
    if target == _GROUP_TARGET:
        # Group propdefs are keyed per group type, so the index predicate is mandatory.
        query = query.filter(type=PropertyDefinition.Type.GROUP, group_type_index=group_type_index)
    else:
        query = query.filter(type=PropertyDefinition.Type.PERSON)

    current_origins = dict(query.filter(name__in=names).values_list("name", "warehouse_origin"))
    missing = [name for name in names if name not in current_origins]
    if missing:
        # Ingestion may create the same effective-project identity after the read above. Ignore that
        # conflict, then read back the winner before deciding which origins still need a write.
        PropertyDefinition.objects.bulk_create(
            [
                PropertyDefinition(
                    team_id=team_id,
                    project_id=project_id,
                    name=name,
                    type=definition_type,
                    group_type_index=definition_group_type_index,
                    warehouse_origin={
                        **origin,
                        **({"description": canonical_descriptions[name]} if canonical_descriptions[name] else {}),
                    },
                )
                for name in missing
            ],
            ignore_conflicts=True,
        )
        current_origins.update(query.filter(name__in=missing).values_list("name", "warehouse_origin"))

    # Replacing the whole origin deliberately clears a previously configured description.
    plain = [name for name in names if not canonical_descriptions[name] and current_origins.get(name) != origin]
    if plain:
        query.filter(name__in=plain).update(warehouse_origin=origin)
    for name in names:
        description = canonical_descriptions[name]
        if not description:
            continue
        described_origin = {**origin, "description": description}
        if current_origins.get(name) != described_origin:
            query.filter(name=name).update(warehouse_origin=described_origin)
