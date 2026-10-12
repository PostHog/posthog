"""Canonical, documentation-sourced descriptions for Rollbar endpoints and columns.

Sourced from the official Rollbar API reference (https://docs.rollbar.com/reference).
Keyed by the endpoint names in `settings.py` `ROLLBAR_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Rollbar table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "items": {
        "description": "An error item grouping together occurrences of the same error in a project.",
        "docs_url": "https://docs.rollbar.com/reference/list-all-items",
        "columns": {
            "id": "Unique identifier for the item.",
            "counter": "Per-project sequential counter for the item.",
            "project_id": "ID of the project the item belongs to.",
            "environment": "Environment the item was reported in (e.g. production).",
            "title": "Title summarizing the error.",
            "level": "Severity level of the item (e.g. error, warning, critical).",
            "status": "Status of the item (e.g. active, resolved, muted).",
            "counter_total": "Total number of occurrences recorded for the item.",
            "occurrences": "Number of occurrences of the item.",
            "first_occurrence_id": "ID of the first occurrence of the item.",
            "first_occurrence_timestamp": "Time of the first occurrence (Unix seconds).",
            "last_occurrence_id": "ID of the most recent occurrence of the item.",
            "last_occurrence_timestamp": "Time of the most recent occurrence (Unix seconds).",
            "last_modified_by": "ID of the user who last modified the item.",
            "framework": "Framework the error originated in.",
            "platform": "Platform the error originated on.",
            "assigned_user_id": "ID of the user the item is assigned to.",
            "resolved_in_version": "Version in which the item was resolved.",
        },
    },
    "occurrences": {
        "description": "A single occurrence (instance) of an error item, with full event details.",
        "docs_url": "https://docs.rollbar.com/reference/list-all-instances",
        "columns": {
            "id": "Unique identifier for the occurrence.",
            "project_id": "ID of the project the occurrence belongs to.",
            "item_id": "ID of the item this occurrence belongs to.",
            "timestamp": "Time the occurrence happened (Unix seconds).",
            "version": "Schema version of the occurrence payload.",
            "billable": "Whether the occurrence counts toward billing.",
            "data": "The full occurrence payload, including the error body and request context.",
        },
    },
    "deploys": {
        "description": "A deployment recorded in Rollbar, marking a release of code to an environment.",
        "docs_url": "https://docs.rollbar.com/reference/list-all-deploys",
        "columns": {
            "id": "Unique identifier for the deploy.",
            "project_id": "ID of the project the deploy belongs to.",
            "environment": "Environment the deploy was made to.",
            "revision": "Source control revision (commit SHA) that was deployed.",
            "comment": "Comment describing the deploy.",
            "user_id": "ID of the user who recorded the deploy.",
            "local_username": "Local username of the person who triggered the deploy.",
            "start_time": "Time the deploy started (Unix seconds).",
            "finish_time": "Time the deploy finished (Unix seconds).",
            "status": "Status of the deploy (e.g. started, succeeded, failed).",
        },
    },
    "environments": {
        "description": "An environment configured in the Rollbar project (e.g. production, staging).",
        "docs_url": "https://docs.rollbar.com/reference",
        "columns": {
            "id": "Unique identifier for the environment.",
            "project_id": "ID of the project the environment belongs to.",
            "name": "The environment's name.",
        },
    },
}
