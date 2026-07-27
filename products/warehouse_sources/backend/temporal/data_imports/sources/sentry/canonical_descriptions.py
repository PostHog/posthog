"""Canonical, documentation-sourced descriptions for Sentry endpoints and columns.

Sourced from the official Sentry API reference (https://docs.sentry.io/api/). Keyed by the
endpoint names in `settings.py` `SENTRY_ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Sentry table. Fanout endpoints add the parent's renamed key columns (e.g. `project_id`,
`issue_id`). Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "A Sentry project that error and performance events are reported to.",
        "docs_url": "https://docs.sentry.io/api/projects/list-your-organizations-projects/",
        "columns": {
            "id": "Unique identifier for the project.",
            "slug": "URL-friendly short name of the project.",
            "name": "Display name of the project.",
            "platform": "Platform the project monitors (e.g. python, javascript).",
            "dateCreated": "Time at which the project was created.",
            "isPublic": "Whether the project is public.",
            "status": "Status of the project (e.g. active, deleted).",
            "team": "The team that owns the project.",
        },
    },
    "teams": {
        "description": "A team within the Sentry organization that owns projects.",
        "docs_url": "https://docs.sentry.io/api/teams/list-an-organizations-teams/",
        "columns": {
            "id": "Unique identifier for the team.",
            "slug": "URL-friendly short name of the team.",
            "name": "Display name of the team.",
            "dateCreated": "Time at which the team was created.",
            "memberCount": "Number of members on the team.",
        },
    },
    "members": {
        "description": "A member of the Sentry organization.",
        "docs_url": "https://docs.sentry.io/api/organizations/list-an-organizations-members/",
        "columns": {
            "id": "Unique identifier for the member.",
            "email": "Email address of the member.",
            "name": "Name of the member.",
            "role": "Organization role of the member (e.g. owner, member).",
            "dateCreated": "Time at which the member was added to the organization.",
            "pending": "Whether the member's invitation is still pending.",
        },
    },
    "releases": {
        "description": "A release tracked in Sentry, used to associate errors with deployed code versions.",
        "docs_url": "https://docs.sentry.io/api/releases/list-an-organizations-releases/",
        "columns": {
            "version": "The release version identifier.",
            "shortVersion": "Shortened, human-readable version identifier.",
            "dateCreated": "Time at which the release was created.",
            "dateReleased": "Time at which the release was deployed.",
            "ref": "VCS reference (e.g. commit) the release points to.",
            "url": "URL associated with the release.",
            "projects": "Projects the release is associated with.",
            "adoption_stages": "Per-project adoption stage of the release (e.g. low_adoption, adopted, replaced).",
        },
    },
    "environments": {
        "description": "An environment (e.g. production, staging) that events are tagged with.",
        "docs_url": "https://docs.sentry.io/api/environments/list-an-organizations-environments/",
        "columns": {
            "id": "Unique identifier for the environment.",
            "name": "Name of the environment.",
        },
    },
    "monitors": {
        "description": "A cron monitor that tracks the health of scheduled jobs.",
        "docs_url": "https://docs.sentry.io/api/crons/retrieve-monitors-for-an-organization/",
        "columns": {
            "id": "Unique identifier for the monitor.",
            "slug": "URL-friendly short name of the monitor.",
            "name": "Display name of the monitor.",
            "status": "Status of the monitor (e.g. active, disabled).",
            "dateCreated": "Time at which the monitor was created.",
            "config": "Schedule and check-in configuration for the monitor.",
        },
    },
    "issues": {
        "description": "A group of similar error events aggregated into a single issue.",
        "docs_url": "https://docs.sentry.io/api/events/list-a-projects-issues/",
        "columns": {
            "id": "Unique identifier for the issue.",
            "shortId": "Human-readable short identifier for the issue.",
            "title": "Title of the issue.",
            "culprit": "Code location or transaction blamed for the issue.",
            "level": "Severity level of the issue (e.g. error, warning).",
            "status": "Status of the issue (e.g. unresolved, resolved, ignored).",
            "count": "Total number of events in the issue.",
            "userCount": "Number of distinct users affected by the issue.",
            "firstSeen": "Time at which the issue was first observed.",
            "lastSeen": "Time at which the issue was most recently observed.",
            "permalink": "Permanent URL to the issue in Sentry.",
            "project": "The project the issue belongs to.",
        },
    },
    "project_events": {
        "description": "Individual error events captured for a project.",
        "docs_url": "https://docs.sentry.io/api/events/list-a-projects-events/",
        "columns": {
            "id": "Unique identifier for the event.",
            "eventID": "The event's identifier.",
            "event_id": "Renamed primary key for the event.",
            "project_id": "ID of the project the event belongs to (from the parent project).",
            "project_slug": "Slug of the project the event belongs to (from the parent project).",
            "title": "Title of the event.",
            "message": "Message associated with the event.",
            "platform": "Platform the event originated from.",
            "dateCreated": "Time at which the event was created.",
            "user": "Information about the user affected by the event.",
            "tags": "Key-value tags attached to the event.",
        },
    },
    "project_users": {
        "description": "Users seen in events for a project.",
        "docs_url": "https://docs.sentry.io/api/projects/list-a-projects-users/",
        "columns": {
            "id": "Unique identifier for the project user.",
            "project_id": "ID of the project the user was seen in (from the parent project).",
            "email": "Email address of the user.",
            "username": "Username of the user.",
            "name": "Name of the user.",
            "ipAddress": "IP address associated with the user.",
        },
    },
    "project_client_keys": {
        "description": "Client (DSN) keys that authenticate event submission to a project.",
        "docs_url": "https://docs.sentry.io/api/projects/list-a-projects-client-keys/",
        "columns": {
            "id": "Unique identifier for the client key.",
            "project_id": "ID of the project the key belongs to (from the parent project).",
            "name": "Name of the client key.",
            "public": "The public portion of the key.",
            "isActive": "Whether the key is active.",
            "dateCreated": "Time at which the key was created.",
            "dsn": "The DSN values (public, secret) for the key.",
        },
    },
    "project_service_hooks": {
        "description": "Service hooks that send a project's events to external services.",
        "docs_url": "https://docs.sentry.io/api/projects/list-a-projects-service-hooks/",
        "columns": {
            "id": "Unique identifier for the service hook.",
            "project_id": "ID of the project the hook belongs to (from the parent project).",
            "url": "URL the hook delivers events to.",
            "status": "Status of the service hook.",
            "events": "Event types the hook is subscribed to.",
            "dateCreated": "Time at which the hook was created.",
        },
    },
    "issue_events": {
        "description": "Individual error events belonging to a specific issue.",
        "docs_url": "https://docs.sentry.io/api/events/list-an-issues-events/",
        "columns": {
            "id": "Unique identifier for the event.",
            "eventID": "The event's identifier.",
            "event_id": "Renamed primary key for the event.",
            "issue_id": "ID of the issue the event belongs to (from the parent issue).",
            "title": "Title of the event.",
            "message": "Message associated with the event.",
            "platform": "Platform the event originated from.",
            "dateCreated": "Time at which the event was created.",
            "user": "Information about the user affected by the event.",
            "tags": "Key-value tags attached to the event.",
        },
    },
    "issue_hashes": {
        "description": "Grouping hashes that determine which events are bucketed into an issue.",
        "docs_url": "https://docs.sentry.io/api/events/list-an-issues-hashes/",
        "columns": {
            "id": "The grouping hash value.",
            "issue_id": "ID of the issue the hash belongs to (from the parent issue).",
            "latestEvent": "The most recent event matching this hash.",
        },
    },
    "issue_tag_values": {
        "description": "The distinct values of a tag observed across an issue's events, with counts.",
        "docs_url": "https://docs.sentry.io/api/events/list-a-tags-values-related-to-an-issue/",
        "columns": {
            "issue_id": "ID of the issue the tag value belongs to (from the parent issue).",
            "tag_key": "The tag key these values belong to.",
            "value": "The tag value.",
            "name": "Human-readable name of the tag value.",
            "count": "Number of events with this tag value.",
            "firstSeen": "Time at which this tag value was first observed.",
            "lastSeen": "Time at which this tag value was most recently observed.",
        },
    },
}
