from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema


@runtime_checkable
class _ReconcilesSchemaMetadata(Protocol):
    """A source that stores discovered column metadata on its schemas.

    Callers check this capability instead of naming the source classes, because importing
    ClickHouseSource loads clickhouse_connect and polars, which web processes must not do at boot.
    """

    def reconcile_schema_metadata(
        self, source: "ExternalDataSource", source_schemas: list["SourceSchema"], team_id: int
    ) -> list[str]: ...


def reconcile_schema_metadata_if_supported(
    source_impl: Any, *, source: "ExternalDataSource", source_schemas: list["SourceSchema"], team_id: int
) -> None:
    if isinstance(source_impl, _ReconcilesSchemaMetadata) and getattr(source_impl, "supports_column_selection", False):
        source_impl.reconcile_schema_metadata(source=source, source_schemas=source_schemas, team_id=team_id)
