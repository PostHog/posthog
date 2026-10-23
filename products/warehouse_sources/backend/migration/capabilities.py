from products.warehouse_sources.backend.facade.source_management import SourceRegistry
from products.warehouse_sources.backend.migration.types import SourceCapabilities
from products.warehouse_sources.backend.types import ExternalDataSourceType


def source_capabilities(source_type: ExternalDataSourceType) -> SourceCapabilities:
    source = SourceRegistry.get_source(source_type)
    config = source.get_source_config
    documented = frozenset(table["name"] for table in source.get_documented_tables())
    return SourceCapabilities(
        release_status=config.releaseStatus,
        unreleased=bool(config.unreleasedSource),
        # An empty list means the tables are unknown until we connect, not that there are none.
        documented_tables=documented or None,
        # Every other source drops unselected columns in the pipeline.
        supports_column_selection=not source.has_managed_hogql_schema,
        supports_row_filters=source.supports_row_filters,
    )
