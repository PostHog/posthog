"""Which schema rows a dual-mode connection can serve live, and how a live-only row is access-checked."""

from products.access_control.backend.facade.contracts import FallbackParent, ObjectAccessRef
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


def is_live_query_eligible(schema_row: ExternalDataSchema) -> bool:
    return bool(schema_row.schema_metadata) and not schema_row.row_filters and not schema_row.masked_columns


def live_only_access_ref(schema_row: ExternalDataSchema) -> ObjectAccessRef:
    """The access-control reference for a live-only table, which has no synced table row.

    It carries the schema id, which no table rule can name, so access resolves from the table's source
    and then the resource defaults.
    """
    return ObjectAccessRef(
        resource="warehouse_table",
        id=str(schema_row.id),
        team_id=schema_row.team_id,
        created_by_id=None,
        fallback_parent=FallbackParent(resource="external_data_source", id=str(schema_row.source_id)),
    )
