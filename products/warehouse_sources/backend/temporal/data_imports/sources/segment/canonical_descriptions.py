from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions are taken from the Twilio Segment Public API docs (https://docs.segmentapis.com). The
# Public API is the workspace configuration/admin/metadata API, not the event or Profile data plane.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workspace": {
        "description": "The Segment workspace associated with the Public API token used to connect.",
        "docs_url": "https://docs.segmentapis.com/tag/Workspaces",
        "columns": {
            "id": "Unique identifier for the workspace.",
            "name": "Human-readable name of the workspace.",
            "slug": "URL-friendly slug for the workspace.",
        },
    },
    "sources": {
        "description": "Sources configured in the workspace — the integrations that send data into Segment.",
        "docs_url": "https://docs.segmentapis.com/tag/Sources",
        "columns": {
            "id": "Unique identifier for the source.",
            "slug": "URL-friendly slug for the source.",
            "name": "Human-readable name of the source.",
            "workspaceId": "Identifier of the workspace the source belongs to.",
            "enabled": "Whether the source is currently enabled.",
            "metadata": "Catalog metadata describing the source type (id, slug, name, categories, logos).",
            "settings": "Source-specific configuration settings.",
            "labels": "Labels applied to the source.",
        },
    },
    "destinations": {
        "description": "Destinations configured in the workspace — where Segment forwards collected data.",
        "docs_url": "https://docs.segmentapis.com/tag/Destinations",
        "columns": {
            "id": "Unique identifier for the destination.",
            "name": "Human-readable name of the destination.",
            "sourceId": "Identifier of the source feeding this destination.",
            "enabled": "Whether the destination is currently enabled.",
            "metadata": "Catalog metadata describing the destination type.",
        },
    },
    "warehouses": {
        "description": "Warehouse connections configured in the workspace (e.g. Redshift, BigQuery, Snowflake).",
        "docs_url": "https://docs.segmentapis.com/tag/Warehouses",
        "columns": {
            "id": "Unique identifier for the warehouse connection.",
            "workspaceId": "Identifier of the workspace the warehouse belongs to.",
            "enabled": "Whether the warehouse connection is currently enabled.",
            "metadata": "Catalog metadata describing the warehouse type.",
        },
    },
    "tracking_plans": {
        "description": "Tracking plans that define the expected events and properties for the workspace.",
        "docs_url": "https://docs.segmentapis.com/tag/Tracking-Plans",
        "columns": {
            "id": "Unique identifier for the tracking plan.",
            "name": "Human-readable name of the tracking plan.",
            "type": "The type of tracking plan.",
            "updatedAt": "When the tracking plan was last updated.",
            "createdAt": "When the tracking plan was created.",
        },
    },
    "transformations": {
        "description": "Transformations that modify events in-flight before they reach destinations.",
        "docs_url": "https://docs.segmentapis.com/tag/Transformations",
        "columns": {
            "id": "Unique identifier for the transformation.",
            "name": "Human-readable name of the transformation.",
            "sourceId": "Identifier of the source the transformation applies to.",
            "enabled": "Whether the transformation is currently enabled.",
        },
    },
    "reverse_etl_models": {
        "description": "Reverse ETL models — the queries that extract data from a warehouse to send to destinations.",
        "docs_url": "https://docs.segmentapis.com/tag/Reverse-ETL",
        "columns": {
            "id": "Unique identifier for the Reverse ETL model.",
            "sourceId": "Identifier of the Reverse ETL source the model belongs to.",
            "name": "Human-readable name of the model.",
            "enabled": "Whether the model is currently enabled.",
            "query": "The SQL query defining the model.",
        },
    },
    "iam_users": {
        "description": "IAM users with access to the workspace.",
        "docs_url": "https://docs.segmentapis.com/tag/IAM-Users",
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "The user's name.",
            "email": "The user's email address.",
        },
    },
    "iam_groups": {
        "description": "IAM user groups defined in the workspace.",
        "docs_url": "https://docs.segmentapis.com/tag/IAM-Groups",
        "columns": {
            "id": "Unique identifier for the user group.",
            "name": "Human-readable name of the group.",
            "memberCount": "Number of members in the group.",
        },
    },
    "labels": {
        "description": "Labels defined in the workspace, used to tag and organize sources and other resources.",
        "docs_url": "https://docs.segmentapis.com/tag/Labels",
        "columns": {
            "key": "The label key (e.g. `environment`).",
            "value": "The label value (e.g. `dev`).",
            "description": "Optional description of the label.",
        },
    },
    "audit_events": {
        "description": "Workspace audit trail — a log of configuration and access events.",
        "docs_url": "https://docs.segmentapis.com/tag/Audit-Trail",
        "columns": {
            "id": "Unique identifier for the audit event.",
            "timestamp": "When the event occurred (ISO 8601).",
            "type": "The type of audit event.",
            "actor": "The user or token that performed the action.",
            "resourceId": "Identifier of the resource the event acted on.",
            "resourceType": "The type of resource the event acted on.",
            "resourceName": "Name of the resource the event acted on.",
        },
    },
}
