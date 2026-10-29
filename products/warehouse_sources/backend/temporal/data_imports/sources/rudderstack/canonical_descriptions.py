from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sources": {
        "description": "Event sources configured in the RudderStack workspace.",
        "docs_url": "https://github.com/rudderlabs/rudder-iac/blob/main/api/client/sources.go",
        "columns": {"id": "Source identifier.", "name": "Source name.", "createdAt": "Source creation timestamp."},
    },
    "destinations": {
        "description": "Destinations configured to receive RudderStack events.",
        "docs_url": "https://github.com/rudderlabs/rudder-iac/blob/main/api/client/destinations.go",
        "columns": {
            "id": "Destination identifier.",
            "type": "Destination type.",
            "createdAt": "Destination creation timestamp.",
        },
    },
    "connections": {
        "description": "Connections between event sources and destinations.",
        "docs_url": "https://github.com/rudderlabs/rudder-iac/blob/main/api/client/connections.go",
        "columns": {
            "id": "Connection identifier.",
            "sourceId": "Connected source identifier.",
            "destinationId": "Connected destination identifier.",
        },
    },
    "transformations": {
        "description": "Published transformations that change events before delivery.",
        "docs_url": "https://www.rudderstack.com/docs/api/transformation-api/",
        "columns": {
            "id": "Transformation identifier.",
            "versionId": "Published version identifier.",
            "code": "Transformation code.",
        },
    },
    "libraries": {
        "description": "Published code libraries for RudderStack transformations.",
        "docs_url": "https://www.rudderstack.com/docs/api/transformation-api/",
        "columns": {
            "id": "Library identifier.",
            "importName": "Name used to import the library.",
            "code": "Library code.",
        },
    },
    "tracking_plans": {
        "description": "Tracking plans that define the expected event data.",
        "docs_url": "https://www.rudderstack.com/docs/api/data-catalog-api/tracking-plans/",
        "columns": {
            "id": "Tracking plan identifier.",
            "version": "Tracking plan version.",
            "createdAt": "Tracking plan creation timestamp.",
        },
    },
    "catalog_events": {
        "description": "Event definitions in the RudderStack data catalog.",
        "docs_url": "https://www.rudderstack.com/docs/api/data-catalog-api/data-catalog/",
        "columns": {
            "id": "Catalog event identifier.",
            "eventType": "Event type.",
            "categoryId": "Catalog category identifier.",
        },
    },
    "catalog_properties": {
        "description": "Property definitions and validation rules in the data catalog.",
        "docs_url": "https://www.rudderstack.com/docs/api/data-catalog-api/data-catalog/",
        "columns": {
            "id": "Property identifier.",
            "type": "Property data type.",
            "propConfig": "Property validation rules.",
        },
    },
    "catalog_categories": {
        "description": "Categories used to organize catalog events.",
        "docs_url": "https://www.rudderstack.com/docs/api/data-catalog-api/data-catalog/",
        "columns": {
            "id": "Category identifier.",
            "name": "Category name.",
            "createdAt": "Category creation timestamp.",
        },
    },
    "audit_logs": {
        "description": "Organization audit logs. Requires an organization Service Access Token and the Enterprise plan.",
        "docs_url": "https://www.rudderstack.com/docs/api/audit-logs-api/",
        "columns": {
            "id": "Audit log identifier.",
            "createdAt": "Audit log creation timestamp.",
            "action": "Action performed on the target.",
        },
    },
    "retl_connections": {
        "description": "Reverse ETL connections that send warehouse data to destinations.",
        "docs_url": "https://github.com/rudderlabs/rudder-iac/blob/main/api/client/retl/connection_types.go",
        "columns": {
            "id": "Reverse ETL connection identifier.",
            "sourceId": "Connected source identifier.",
            "destinationId": "Connected destination identifier.",
        },
    },
    "retl_syncs": {
        "description": "Reverse ETL sync history, status, and delivery metrics for each connection.",
        "docs_url": "https://www.rudderstack.com/docs/api/retl-connections-api/",
        "columns": {
            "id": "Sync identifier within the connection.",
            "connection_id": "Reverse ETL connection identifier.",
            "startedAt": "Sync start timestamp.",
            "metrics": "Counts of changed, succeeded, and failed records.",
        },
    },
}
