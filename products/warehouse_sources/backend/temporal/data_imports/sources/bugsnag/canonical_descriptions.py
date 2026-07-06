from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the BugSnag Data Access API docs (https://bugsnagapiv2.docs.apiary.io/). Partial
# coverage is fine — any endpoint, column, or table missing here falls back to LLM enrichment.
# `organization_id` / `project_id` are injected by this connector during fan-out, not returned by
# the API, so they're documented alongside the API's own fields.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "organizations": {
        "description": "An organization the auth token can access; the top of BugSnag's resource hierarchy, owning projects and collaborators.",
        "docs_url": "https://bugsnagapiv2.docs.apiary.io/#reference/organizations",
        "columns": {
            "id": "Unique identifier for the organization.",
            "name": "Display name of the organization.",
            "slug": "URL-friendly slug for the organization.",
            "created_at": "When the organization was created.",
            "updated_at": "When the organization was last updated.",
        },
    },
    "projects": {
        "description": "An application or service monitored in BugSnag. Errors and events are scoped to a project.",
        "docs_url": "https://bugsnagapiv2.docs.apiary.io/#reference/projects",
        "columns": {
            "id": "Unique identifier for the project.",
            "organization_id": "Identifier of the organization that owns the project (injected by the connector).",
            "name": "Display name of the project.",
            "slug": "URL-friendly slug for the project.",
            "api_key": "Notifier API key used by BugSnag SDKs to send events to this project.",
            "type": "Platform/framework of the project (e.g. js, rails, android).",
            "created_at": "When the project was created.",
            "updated_at": "When the project was last updated.",
            "errors_url": "API URL for the project's errors.",
            "events_url": "API URL for the project's events.",
        },
    },
    "collaborators": {
        "description": "A user with access to an organization in BugSnag.",
        "docs_url": "https://bugsnagapiv2.docs.apiary.io/#reference/collaborators",
        "columns": {
            "id": "Unique identifier for the collaborator.",
            "organization_id": "Identifier of the organization the collaborator belongs to (injected by the connector).",
            "name": "Collaborator's display name.",
            "email": "Collaborator's email address.",
        },
    },
    "teams": {
        "description": "A team within an organization, used to group collaborators and scope project access.",
        "docs_url": "https://bugsnagapiv2.docs.apiary.io/#reference/teams",
        "columns": {
            "id": "Unique identifier for the team.",
            "organization_id": "Identifier of the organization the team belongs to (injected by the connector).",
            "name": "Team name.",
        },
    },
    "errors": {
        "description": "A group of similar events (a distinct error) in a project, with aggregate counts and first/last-seen timestamps.",
        "docs_url": "https://bugsnagapiv2.docs.apiary.io/#reference/errors",
        "columns": {
            "id": "Unique identifier for the error.",
            "project_id": "Identifier of the project the error belongs to (injected by the connector).",
            "error_class": "Class/type of the error (e.g. RuntimeError).",
            "message": "Representative error message.",
            "context": "Context the error occurred in (e.g. the controller/route).",
            "severity": "Severity of the error (error, warning, info).",
            "status": "Workflow status of the error (open, fixed, ignored, snoozed).",
            "first_seen": "When the error was first seen.",
            "last_seen": "When the error was most recently seen.",
            "events": "Total number of events recorded for this error.",
            "users": "Number of distinct users affected by this error.",
        },
    },
    "events": {
        "description": "An individual occurrence (a single crash/exception report) within a project.",
        "docs_url": "https://bugsnagapiv2.docs.apiary.io/#reference/events",
        "columns": {
            "id": "Unique identifier for the event.",
            "project_id": "Identifier of the project the event belongs to (injected by the connector).",
            "error_id": "Identifier of the error this event belongs to.",
            "received_at": "When BugSnag received the event.",
            "severity": "Severity reported for the event.",
            "context": "Context the event occurred in.",
            "unhandled": "Whether the event was an unhandled error.",
            "app": "App metadata recorded with the event (version, release stage, …).",
            "device": "Device metadata recorded with the event.",
            "user": "User metadata recorded with the event.",
        },
    },
    "releases": {
        "description": "A released version of a project's app, with stability and event metrics.",
        "docs_url": "https://bugsnagapiv2.docs.apiary.io/#reference/releases",
        "columns": {
            "id": "Unique identifier for the release.",
            "project_id": "Identifier of the project the release belongs to (injected by the connector).",
            "release_stage_name": "Release stage (e.g. production, staging).",
            "app_version": "Application version string for the release.",
            "released_at": "When the release was made.",
            "first_released_at": "When this version was first released.",
            "total_sessions_count": "Number of sessions recorded for the release.",
            "unhandled_sessions_count": "Number of sessions with an unhandled error.",
        },
    },
    "saved_searches": {
        "description": "A saved error filter/search defined in a project.",
        "docs_url": "https://bugsnagapiv2.docs.apiary.io/#reference/saved-searches",
        "columns": {
            "id": "Unique identifier for the saved search.",
            "project_id": "Identifier of the project the saved search belongs to (injected by the connector).",
            "name": "Name of the saved search.",
        },
    },
}
