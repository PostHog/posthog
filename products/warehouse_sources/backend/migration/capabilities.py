from functools import cache

from products.warehouse_sources.backend.facade.source_config import (
    SourceFieldSSHTunnelConfig,
    SourceFieldSwitchGroupConfig,
)
from products.warehouse_sources.backend.facade.source_management import SourceRegistry
from products.warehouse_sources.backend.migration.types import SourceCapabilities
from products.warehouse_sources.backend.types import ExternalDataSourceType


@cache
def source_capabilities(source_type: ExternalDataSourceType) -> SourceCapabilities:
    source = SourceRegistry.get_source(source_type)
    config = source.get_source_config
    # Canonical descriptions are not a full table list (Firebase tables are the user's own collections),
    # so a source that lists tables only with credentials counts as unknown until PostHog connects.
    documented = frozenset(table["name"] for table in source.get_documented_tables())
    row_filter_columns = {}
    if source.supports_row_filters:
        for table in documented:
            columns = source.row_filter_columns_for_schema(table)
            if columns is not None:
                row_filter_columns[table] = frozenset(column.name for column in columns)
    return SourceCapabilities(
        release_status=config.releaseStatus,
        unreleased=bool(config.unreleasedSource),
        # An empty set means the tables are unknown until we connect, not that there are none.
        documented_tables=documented or None,
        # Apply can only exclude columns that discovery lists, and only these sources list them.
        supports_column_selection=source.supports_column_selection and not source.has_managed_hogql_schema,
        supports_row_filters=source.supports_row_filters,
        row_filter_columns=row_filter_columns,
        toggle_groups=frozenset(
            field.name
            for field in config.fields
            if isinstance(field, SourceFieldSwitchGroupConfig | SourceFieldSSHTunnelConfig)
        ),
        feature_flags=frozenset(flag for flag in (config.featureFlag, source.requires_team_feature_flag) if flag),
    )
