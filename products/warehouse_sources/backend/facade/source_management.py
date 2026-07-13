"""
Source-management wiring for warehouse_sources.

Re-exports the source classes, source registry, CDC adapters, schema/config types, and
row-filter helpers that the data_warehouse source/schema management API uses to validate,
preview, and configure data sources. These live deep under ``temporal.data_imports.sources``
and pull heavy dependencies (DB drivers, the source registry), so this module is loaded
lazily (PEP 562): names resolve on first access, keeping it off the ``django.setup()``
path and out of any import cycle.
"""

_B = "products.warehouse_sources.backend.temporal.data_imports."

_LAZY = {
    "SourceRegistry": "sources",
    "DocsFetchError": "sources.custom.ai_builder",
    "draft_manifest_sync": "sources.custom.ai_builder",
    "fetch_docs_text": "sources.custom.ai_builder",
    "CDCSourceAdapter": "cdc.adapters",
    "get_cdc_adapter": "cdc.adapters",
    "source_type_supports_cdc": "cdc.adapters",
    "CDCRepairError": "cdc.repair",
    "CDCRepairInProgress": "cdc.repair",
    "repair_cdc_source": "cdc.repair",
    "ClickHouseSource": "sources.clickhouse.source",
    "AnySource": "sources.common.base",
    "ExternalWebhookInfo": "sources.common.base",
    "FieldType": "sources.common.base",
    "WebhookCreationResult": "sources.common.base",
    "WebhookDeletionResult": "sources.common.base",
    "WebhookSource": "sources.common.base",
    "WebhookSyncResult": "sources.common.base",
    "Config": "sources.common.config",
    "IntegrationAccountListingError": "sources.common.integration_accounts",
    "OAuthMixin": "sources.common.mixins",
    "SourceSchema": "sources.common.schema",
    "build_default_schemas": "sources.common.schema",
    "RowFilterValidationError": "sources.common.sql",
    "filter_dwh_columns_by_enabled_columns": "sources.common.sql",
    "sql_schema_metadata": "sources.common.sql",
    "validate_and_coerce_row_filters": "sources.common.sql",
    "SQLSource": "sources.common.sql.base",
    "extract_available_column_names": "sources.common.sql.metadata",
    "fill_missing_from_dotted_name": "sources.common.sql.location",
    "normalize_namespace": "sources.common.sql.location",
    "filter_columns_by_enabled_columns": "sources.common.sql.projection",
    "prune_enabled_columns": "sources.common.sql.projection",
    "template": "sources.common.default_webhook_template",
    "MAX_CUSTOM_SOURCES_PER_TEAM": "sources.custom.source",
    "PREVIEW_DEFAULT_ROWS": "sources.custom.source",
    "PREVIEW_MAX_ROWS": "sources.custom.source",
    "CustomSource": "sources.custom.source",
    "manifest_request_hosts": "sources.custom.source",
    "CustomSourceConfig": "sources.generated_configs",
    "MySQLSourceConfig": "sources.generated_configs",
    "PostgresSourceConfig": "sources.generated_configs",
    "SnowflakeSourceConfig": "sources.generated_configs",
    "MySQLSource": "sources.mysql.source",
    "google_search_console_session": "sources.google_search_console.google_search_console",
    "list_sites": "sources.google_search_console.google_search_console",
    "DEFAULT_LAG_CRITICAL_THRESHOLD_MB": "sources.postgres.cdc.config",
    "DEFAULT_LAG_WARNING_THRESHOLD_MB": "sources.postgres.cdc.config",
    "cdc_pg_connection": "sources.postgres.cdc.slot_manager",
    "SSLRequiredError": "sources.postgres.postgres",
    "SSL_REQUIRED_AFTER_DATE": "sources.postgres.postgres",
    "_get_sslmode": "sources.postgres.postgres",
    "get_primary_key_columns": "sources.postgres.postgres",
    "source_requires_ssl": "sources.postgres.postgres",
    "PostgresSource": "sources.postgres.source",
    "SnowflakeSource": "sources.snowflake.source",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)
