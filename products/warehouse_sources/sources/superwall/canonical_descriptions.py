from products.warehouse_sources.sources.sdk import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "paywalls": {
        "description": "Paywalls for the application, including their products and presentation settings.",
        "docs_url": "https://api.superwall.com/docs",
        "columns": {
            "id": "Unique paywall identifier.",
            "application_id": "Application that owns the paywall.",
            "created_at": "ISO 8601 timestamp when the paywall was created.",
            "updated_at": "ISO 8601 timestamp when the paywall was last updated.",
        },
    },
    "campaigns": {
        "description": "Campaigns for the application, including placements, audiences, and delivery settings.",
        "docs_url": "https://api.superwall.com/docs",
        "columns": {
            "id": "Unique campaign identifier.",
            "application_id": "Application that owns the campaign.",
            "created_at": "ISO 8601 timestamp when the campaign was created.",
        },
    },
    "products": {
        "description": "Products for the project, including store identifiers, prices, and subscription details.",
        "docs_url": "https://api.superwall.com/docs",
        "columns": {
            "id": "Unique product identifier.",
            "project_id": "Project that owns the product.",
            "created_at": "ISO 8601 timestamp when the product was created.",
        },
    },
    "entitlements": {
        "description": "Entitlements for the project and the products that provide them.",
        "docs_url": "https://api.superwall.com/docs",
        "columns": {
            "id": "Unique entitlement identifier.",
            "project_id": "Project that owns the entitlement.",
            "created_at": "ISO 8601 timestamp when the entitlement was created.",
        },
    },
    "surveys": {
        "description": "Non-archived surveys for the application, including questions and response options.",
        "docs_url": "https://api.superwall.com/docs",
        "columns": {
            "id": "Unique survey identifier.",
            "application_id": "Application that owns the survey.",
            "created_at": "ISO 8601 timestamp when the survey was created.",
        },
    },
    "webhook_events": {
        "description": "Webhook event messages retained for the project, including their payloads and delivery channels.",
        "docs_url": "https://api.superwall.com/docs",
        "columns": {
            "id": "Unique webhook message identifier.",
            "event_id": "Identifier of the underlying event.",
            "event_type": "Type of event that triggered the message.",
            "timestamp": "Timestamp of the event message.",
            "payload": "Event message payload.",
        },
    },
    "projects": {
        "description": "Projects in the organization and the applications that belong to each one.",
        "docs_url": "https://api.superwall.com/docs",
        "columns": {
            "id": "Unique project identifier.",
            "name": "Display name of the project.",
            "organization_id": "ID of the organization that owns this project.",
            "applications": "Applications in the project, with their platform, bundle ID and store app ID.",
            "archived": "Whether the project is archived.",
            "metadata": "Arbitrary key-value metadata attached to the project.",
            "created_at": "ISO 8601 timestamp when the project was created.",
            "updated_at": "ISO 8601 timestamp when the project was last updated.",
        },
    },
    "entitlement_grants": {
        "description": "Manual grants of each entitlement to users or devices, including expired and revoked grants.",
        "docs_url": "https://api.superwall.com/docs",
        "columns": {
            "id": "Unique grant identifier.",
            "entitlement": "ID of the entitlement that the grant gives.",
            "entitlement_identifier": "Identifier string of the entitlement being granted.",
            "user_id": "User ID the grant applies to, or null.",
            "device_id": "Device ID the grant applies to, or null when it applies to the user on every device.",
            "expires_at": "ISO 8601 timestamp when the grant expires, or null for permanent grants.",
            "reason": "Reason for the grant, or null.",
            "granted_by": "Identifier of who granted this entitlement.",
            "granted_at": "ISO 8601 timestamp when the grant was created.",
            "status": "Current status of the grant: active, expired, or revoked.",
        },
    },
    "audit_logs": {
        "description": "Audit log entries for requests that changed state in the organization, newest first, with the changes they made.",
        "docs_url": "https://api.superwall.com/docs",
        "columns": {
            "id": "Unique audit log entry identifier (UUID).",
            "timestamp": "ISO 8601 timestamp of when the request was served.",
            "method": "HTTP method of the request.",
            "path": "URL path with query string.",
            "endpoint_id": "Resolved OpenAPI endpoint name, such as listPaywalls.",
            "auth_method": "Authentication method that succeeded, or null if the request was unauthenticated.",
            "user_id": "ID of the acting user, when authenticated with a cookie or OAuth.",
            "token_id": "ID of the API token, when authenticated with an API key.",
            "organization_id": "Organization the request was scoped to.",
            "authorized": "Whether the request cleared the authentication and authorization checks.",
            "status_code": "HTTP response status code.",
            "mutation": "Whether the endpoint changes state.",
            "resource_type": "Type of the resource that the request changed.",
            "resource_id": "ID of the resource that the request changed.",
            "changes": "Diff operations that describe what the request changed.",
        },
    },
}
