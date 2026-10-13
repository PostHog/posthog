from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Workspaces": {
        "description": "A Bigeye workspace: an isolated collection of connected data sources, tables, and metrics.",
        "docs_url": "https://docs.bigeye.com/reference/workspaceservice_getallworkspaces-1",
        "columns": {
            "id": "Unique identifier for the workspace.",
            "name": "Display name of the workspace.",
            "isDefault": "Whether this is the account's default workspace.",
        },
    },
    "Sources": {
        "description": "A data source (database or warehouse) connected to Bigeye for monitoring.",
        "docs_url": "https://docs.bigeye.com/reference/sourceservice_getsources-1",
        "columns": {
            "id": "Unique identifier for the source.",
            "name": "Display name of the source.",
            "databaseType": "The underlying database or warehouse technology (e.g. Snowflake, BigQuery, Postgres).",
            "hostname": "Hostname Bigeye connects to for this source.",
            "databaseName": "Name of the database or catalog within the source.",
            "isFavorite": "Whether the source is marked as a favorite in the Bigeye UI.",
            "usesAgent": "Whether this source connects through a self-hosted Bigeye agent instead of directly.",
            "agentHealthStatus": "Health status of the connecting agent, when one is used.",
        },
    },
    "Tables": {
        "description": "A table or view discovered by Bigeye within a connected source.",
        "docs_url": "https://docs.bigeye.com/reference/tableservice_gettables-1",
        "columns": {
            "id": "Unique identifier for the table.",
            "name": "Table name.",
            "schemaId": "Identifier of the schema the table belongs to.",
            "schemaName": "Name of the schema the table belongs to.",
            "warehouseId": "Identifier of the source (warehouse) the table belongs to.",
            "warehouseName": "Name of the source (warehouse) the table belongs to.",
            "databaseName": "Name of the database the table belongs to.",
            "tableType": "Whether this is a table, view, or another object type.",
            "isFavorite": "Whether the table is marked as a favorite in the Bigeye UI.",
            "logicalSizeBytes": "Logical size of the table in bytes, as last observed.",
        },
    },
    "Metrics": {
        "description": "A configured data quality metric (a check Bigeye runs on a column or table).",
        "docs_url": "https://docs.bigeye.com/reference/metricservice_searchmetricconfiguration-1",
        "columns": {
            "id": "Unique identifier for the metric.",
            "name": "Display name of the metric.",
            "description": "Free-text description of what the metric checks.",
            "datasetId": "Identifier of the table the metric observes.",
            "warehouseId": "Identifier of the source the metric's table belongs to.",
            "mutedUntilEpochSeconds": "Unix timestamp (seconds) the metric's alerts are muted until, if muted.",
        },
    },
    "Collections": {
        "description": "A named group of metrics, used to organize monitoring and route alert notifications.",
        "docs_url": "https://docs.bigeye.com/reference/collectionservice_getcollectioninfos-1",
        "columns": {
            "id": "Unique identifier for the collection.",
            "name": "Display name of the collection.",
        },
    },
    "Issues": {
        "description": "An open or resolved data quality issue, created when one of a collection's metrics alerts.",
        "docs_url": "https://docs.bigeye.com/reference/issueservice_getissues-1",
        "columns": {
            "id": "Unique identifier for the issue.",
            "name": "Short display name of the issue.",
            "summary": "One-line summary of the issue.",
            "description": "Longer free-text description of the issue.",
            "currentStatus": "Current triage status of the issue (e.g. new, acknowledged, monitoring, resolved).",
            "priority": "Priority Bigeye assigned to the issue.",
            "openedTimeSeconds": "Unix timestamp (seconds) the issue was first opened.",
            "closedTimeSeconds": "Unix timestamp (seconds) the issue was closed, if resolved.",
            "metricIds": "Identifiers of the metrics alerting on this issue.",
        },
    },
}
