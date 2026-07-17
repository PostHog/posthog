from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions are taken from the Instatus REST API docs (https://instatus.com/help/api). The
# "page_id" column on every page-scoped table is injected by the connector (it carries the parent
# status page id), so it is documented here even though it isn't part of the raw list payload.
_PAGE_ID_COLUMN = "Identifier of the status page this record belongs to (added by the connector)."
_DOCS = "https://instatus.com/help/api"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "pages": {
        "description": "The status pages in your Instatus account.",
        "docs_url": f"{_DOCS}/status-pages",
        "columns": {
            "id": "Unique identifier for the status page.",
            "name": "Display name of the status page.",
            "subdomain": "Instatus subdomain for the page (e.g. mycompany in mycompany.instatus.com).",
            "customDomain": "Custom domain mapped to the status page, if configured.",
            "websiteUrl": "URL of the website the status page relates to.",
            "status": "Current overall status of the page (e.g. UP, HASISSUES, UNDERMAINTENANCE).",
            "language": "Language of the status page as a language code (e.g. `en`).",
            "createdAt": "Timestamp when the status page was created.",
            "updatedAt": "Timestamp when the status page was last updated.",
        },
    },
    "components": {
        "description": "Individual services or features whose status is shown on a status page.",
        "docs_url": f"{_DOCS}/components",
        "columns": {
            "id": "Unique identifier for the component.",
            "page_id": _PAGE_ID_COLUMN,
            "name": "Display name of the component.",
            "description": "Description of the component.",
            "status": "Current status (OPERATIONAL, UNDERMAINTENANCE, DEGRADEDPERFORMANCE, PARTIALOUTAGE, MAJOROUTAGE).",
            "order": "Display order of the component on the status page.",
            "groupId": "Identifier of the parent component group, if any.",
            "showUptime": "Whether the uptime percentage and bar are shown for the component.",
            "createdAt": "Timestamp when the component was created.",
            "updatedAt": "Timestamp when the component was last updated.",
        },
    },
    "incidents": {
        "description": "Incidents published to a status page.",
        "docs_url": f"{_DOCS}/incidents",
        "columns": {
            "id": "Unique identifier for the incident.",
            "page_id": _PAGE_ID_COLUMN,
            "name": "Title of the incident.",
            "status": "Current incident status (INVESTIGATING, IDENTIFIED, MONITORING, RESOLVED).",
            "started": "Timestamp when the incident started.",
            "duration": "Duration of the incident in minutes, or null if unresolved.",
            "resolved": "Timestamp when the incident was resolved, or null if unresolved.",
            "updates": "List of updates posted to the incident.",
            "components": "Components affected by the incident.",
        },
    },
    "maintenances": {
        "description": "Scheduled maintenances published to a status page.",
        "docs_url": f"{_DOCS}/maintenances",
        "columns": {
            "id": "Unique identifier for the maintenance.",
            "page_id": _PAGE_ID_COLUMN,
            "name": "Title of the maintenance.",
            "status": "Current maintenance status (NOTSTARTEDYET, INPROGRESS, COMPLETED).",
            "start": "Scheduled start time of the maintenance.",
            "duration": "Duration of the maintenance in minutes, or null if not completed.",
            "autoStart": "Whether the maintenance starts automatically at the scheduled time.",
            "autoEnd": "Whether the maintenance ends automatically at the scheduled end time.",
            "updates": "List of updates posted to the maintenance.",
            "components": "Components affected by the maintenance.",
        },
    },
    "subscribers": {
        "description": "People subscribed to notifications for a status page.",
        "docs_url": f"{_DOCS}/subscribers",
        "columns": {
            "id": "Unique identifier for the subscriber.",
            "page_id": _PAGE_ID_COLUMN,
            "email": "Email address of the subscriber, if an email subscriber.",
            "phone": "Phone number of the subscriber, if an SMS subscriber.",
            "webhook": "Webhook URL of the subscriber, if a webhook subscriber.",
            "confirmed": "Whether the subscriber has confirmed their subscription.",
            "all": "Whether the subscriber is subscribed to all components on the page.",
            "components": "Ids of the specific components the subscriber follows.",
        },
    },
    "metrics": {
        "description": "Custom metrics displayed on a status page (e.g. response time, uptime).",
        "docs_url": f"{_DOCS}/metrics",
        "columns": {
            "id": "Unique identifier for the metric.",
            "page_id": _PAGE_ID_COLUMN,
            "name": "Name of the metric.",
            "active": "Whether the metric is shown in the page's system metrics section.",
            "order": "Display order of the metric on the status page.",
            "suffix": "Suffix appended to the metric value when displayed (e.g. ms).",
        },
    },
    "templates": {
        "description": "Reusable incident and maintenance templates for a status page.",
        "docs_url": f"{_DOCS}/templates",
        "columns": {
            "id": "Unique identifier for the template.",
            "page_id": _PAGE_ID_COLUMN,
            "type": "Whether the template creates incidents or maintenances.",
            "name": "Name of the notice the template creates.",
            "message": "Message used for the first update of the notice.",
            "status": "Default status applied by the template.",
            "notify": "Whether subscribers are notified when the template is used.",
            "createdAt": "Timestamp when the template was created.",
        },
    },
    "team": {
        "description": "Teammates with access to a status page.",
        "docs_url": f"{_DOCS}/teammates",
        "columns": {
            "id": "Unique identifier for the teammate record.",
            "page_id": _PAGE_ID_COLUMN,
            "user": "The user account details of the teammate.",
        },
    },
    "audience_groups": {
        "description": "Audience groups used to target subscribers on a private status page.",
        "docs_url": f"{_DOCS}/audience-groups",
        "columns": {
            "id": "Unique identifier for the audience group.",
            "page_id": _PAGE_ID_COLUMN,
            "siteId": "Identifier of the status page (site) the group belongs to.",
            "name": "Name of the audience group.",
            "teammates": "Teammates that belong to the audience group.",
            "components": "Components associated with the audience group.",
        },
    },
}
