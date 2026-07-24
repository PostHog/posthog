from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Messages": {
        "description": "A message you've sent through Courier, with its current delivery status and engagement timestamps.",
        "docs_url": "https://www.courier.com/docs/reference/messages/list",
        "columns": {
            "id": "Unique identifier associated with the message (the result from a /send or /send/list call).",
            "enqueued": "UTC timestamp at which Courier received the message request.",
            "event": "Unique identifier associated with the event that triggered the message.",
            "notification": "Unique identifier associated with the notification used to send the message.",
            "recipient": "Unique identifier associated with the recipient of the message.",
            "status": "Current status of the message (e.g. ENQUEUED, SENT, DELIVERED, OPENED, CLICKED, UNDELIVERABLE).",
            "clicked": "UTC timestamp at which the recipient first clicked a tracked link, if any.",
            "delivered": "UTC timestamp at which the integration provider delivered the message, if any.",
            "error": "Message describing the error that occurred, if the send failed.",
            "opened": "UTC timestamp at which the recipient first opened the message, if any.",
            "reason": "Reason for the current status (e.g. BOUNCED, FILTERED, UNSUBSCRIBED, PROVIDER_ERROR), if applicable.",
            "sent": "UTC timestamp at which Courier passed the message to the integration provider, if any.",
        },
    },
    "AuditEvents": {
        "description": "An account-level activity log entry recording an action taken by a user or API key in your Courier workspace.",
        "docs_url": "https://www.courier.com/docs/reference/audit-events/list",
        "columns": {
            "auditEventId": "Unique identifier for the audit event.",
            "actor": "The user or API key that performed the action, including their id and email.",
            "source": "The origin of the action (e.g. dashboard, api).",
            "target": "The resource the action was performed on.",
            "timestamp": "UTC timestamp at which the action occurred.",
            "type": "The type of action that was performed (e.g. resource.created, resource.updated).",
        },
    },
    "Audiences": {
        "description": "A saved, filter-defined segment of recipients used to target notifications.",
        "docs_url": "https://www.courier.com/docs/reference/audiences/list",
        "columns": {
            "id": "Unique identifier for the audience.",
            "name": "Name of the audience.",
            "description": "Description of the audience.",
            "created_at": "Timestamp at which the audience was created.",
            "updated_at": "Timestamp at which the audience was last updated.",
            "filter": "Filter configuration (rules and operator) defining audience membership.",
            "operator": "Logical operator (AND/OR) combining the top-level filter rules.",
        },
    },
    "Brands": {
        "description": "A branding profile (colors, logo, templates) that can be applied to messages sent through Courier.",
        "docs_url": "https://www.courier.com/docs/reference/brands/list",
        "columns": {
            "id": "Unique identifier for the brand.",
            "name": "Name of the brand.",
            "created": "Timestamp at which the brand was created.",
            "updated": "Timestamp at which the brand was last updated.",
            "published": "Timestamp at which the brand was last published, if any.",
            "settings": "Brand settings, including email and in-app configuration.",
            "snippets": "Reusable Handlebars snippets available to templates using this brand.",
            "version": "Version identifier of the brand.",
        },
    },
    "Tenants": {
        "description": "A tenant used to scope notification sending and preferences for a group of recipients (e.g. a customer account).",
        "docs_url": "https://www.courier.com/docs/reference/tenants/list",
        "columns": {
            "id": "Unique identifier for the tenant.",
            "name": "Name of the tenant.",
            "brand_id": "Brand used for the tenant when one is not specified by the send call.",
            "parent_tenant_id": "Parent tenant's id, if this tenant is nested under another.",
            "properties": "Arbitrary properties accessible to a template.",
            "user_profile": "A user profile object merged with the recipient's profile on send.",
            "default_preferences": "Notification preferences used for the tenant when the recipient hasn't specified their own.",
        },
    },
}
