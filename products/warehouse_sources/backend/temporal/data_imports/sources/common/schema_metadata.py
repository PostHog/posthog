from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema


@runtime_checkable
class ReconcilesSchemaMetadata(Protocol):
    """A source that stores discovered column metadata on its schemas.

    Callers check this capability instead of naming the source classes, because importing
    ClickHouseSource loads clickhouse_connect and polars, which web processes must not do at boot.
    """

    def reconcile_schema_metadata(
        self, source: "ExternalDataSource", source_schemas: list["SourceSchema"], team_id: int
    ) -> list[str]: ...
