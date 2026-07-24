"""Canonical, documentation-sourced descriptions for Metaplane endpoints and columns.

Sourced from the official Metaplane API reference (https://docs.metaplane.dev/reference).
Keyed by the endpoint names in `settings.py` `METAPLANE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Metaplane table. Columns absent here fall back to LLM
enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "connections": {
        "description": "A data source or tool connected to Metaplane (warehouse, transformation tool, BI tool, ...).",
        "docs_url": "https://docs.metaplane.dev/reference/getallconnections",
        "columns": {
            "id": "Unique identifier (UUID) for the connection.",
            "name": "Display name of the connection.",
            "type": "Kind of connected system (e.g. SNOWFLAKE, BIGQUERY, POSTGRES, DBT, LOOKER).",
            "isEnabled": "Whether the connection is currently enabled.",
            "createdAt": "Time at which the connection was created.",
            "updatedAt": "Time at which the connection was last updated.",
            "status": "Lifecycle status of the connection (ACTIVE or DELETED).",
        },
    },
    "monitors": {
        "description": "A data-quality monitor watching a database, schema, table, or column (row count, freshness, nullness, ...).",
        "docs_url": "https://docs.metaplane.dev/reference/getallmonitorsforsource",
        "columns": {
            "id": "Unique identifier (UUID) for the monitor.",
            "type": "Metric the monitor tracks (e.g. ROW_COUNT, FRESHNESS, NULLNESS, CARDINALITY, CUSTOM).",
            "valueType": "Data type of the monitored value.",
            "cronTab": "Cron expression controlling when the monitor runs.",
            "name": "Display name of the monitor.",
            "description": "User-supplied description of the monitor.",
            "isEnabled": "Whether the monitor is currently enabled.",
            "config": "Monitor configuration (custom SQL, incremental clause, where clause, alert rule, group-by columns, time zone).",
            "createdAt": "Time at which the monitor was created.",
            "updatedAt": "Time at which the monitor was last updated.",
            "absolutePath": "Absolute path of the monitored entity, like {database}.{schema}.{table}.{column}.",
            "entityType": "Kind of entity the monitor targets (database, schema, table, or column).",
            "connectionId": "ID of the connection the monitored entity belongs to.",
            "monitorTags": "Tags applied to the monitor.",
            "monitorGroups": "Group-by groupings for group-by monitors.",
        },
    },
    "monitor_evaluations": {
        "description": "A single evaluation (run) of a monitor: the measured value, the model's expected bounds, and whether it passed.",
        "docs_url": "https://docs.metaplane.dev/reference/getevaluationhistory",
        "columns": {
            "monitorId": "ID of the monitor this evaluation belongs to.",
            "createdAt": "Time at which the evaluation was created.",
            "result": "Measured value of the monitored metric at evaluation time.",
            "lowerBound": "Lower bound of the model's expected range for this evaluation.",
            "upperBound": "Upper bound of the model's expected range for this evaluation.",
            "predicted": "Value the model predicted for this evaluation.",
            "passed": "Whether the evaluation passed (the measured value fell within the expected bounds).",
            "status": "Outcome of the evaluation (PASS, FAIL, IN_TRAINING, FAILED_TO_PREDICT, NOT_ENOUGH_DATA, ERROR, INVALID_INPUT).",
            "openRelatedIncidents": "IDs of currently active incidents related to this evaluation.",
            "errorMessage": "Error message when the evaluation failed to run.",
            "annotation": "Optional user annotation applied to this datapoint (e.g. FALSE_POSITIVE, NEW_BASELINE).",
        },
    },
    "connection_sync_statuses": {
        "description": "The latest metadata-sync outcome for each connection.",
        "docs_url": "https://docs.metaplane.dev/reference/getconnectionstatus",
        "columns": {
            "connectionId": "ID of the connection the sync status belongs to.",
            "status": "Outcome of the most recent sync (STARTED, SUCCEEDED, or ERRORED).",
            "errorMessage": "Error message when the most recent sync errored.",
            "timestamp": "Time of the most recent sync status change.",
        },
    },
}
