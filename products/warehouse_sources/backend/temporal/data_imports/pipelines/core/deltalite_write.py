"""Per-schema feature-flag gating for the deltalite real-write path (phase 2).

When the ``data-warehouse-deltalite-write`` flag matches a schema, deltalite performs the incremental
merge (``DeltaLiteTable.upsert``) instead of the delta-rs ``MERGE`` — see
``DeltaTableHelper._write_via_deltalite``. A deltalite failure falls back to the MERGE, so the flag
only ever changes *which engine* writes, never whether the sync succeeds.
"""

import posthoganalytics

WAREHOUSE_DELTALITE_WRITE_FLAG = "data-warehouse-deltalite-write"


def is_deltalite_write_enabled(team_id: int, schema_id: str, source_type: str | None = None) -> bool:
    """Evaluate the per-schema deltalite write rollout flag.

    ``schema_id`` / ``team_id`` / ``source_type`` are passed as person properties so the flag can be
    released to a single table first (release condition ``schema_id = <id>``) before ramping by team /
    org / source. Mirrors ``is_auto_repartition_enabled``. This flag is the only control (no env
    switch), so the write path can be ramped or killed from the flag UI without a deploy. Any
    evaluation failure returns False (fail closed): a flags-service blip must never accidentally switch
    it on.
    """
    from posthog.models import Team

    try:
        team = Team.objects.only("uuid", "organization_id").get(id=team_id)
    except Team.DoesNotExist:
        return False

    # Resolve source_type from the schema when the caller didn't supply it, so a `source_type = <x>`
    # release condition can actually match. Best-effort: a lookup failure just omits the property.
    if source_type is None:
        try:
            from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

            schema = ExternalDataSchema.objects.select_related("source").get(id=schema_id)
            source_type = schema.source.source_type
        except Exception:
            source_type = None

    person_properties: dict[str, str] = {"schema_id": str(schema_id), "team_id": str(team_id)}
    if source_type is not None:
        person_properties["source_type"] = source_type

    try:
        return bool(
            posthoganalytics.feature_enabled(
                WAREHOUSE_DELTALITE_WRITE_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team_id)},
                person_properties=person_properties,
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team_id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False
