from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "checks": {
        "description": "Monitoring checks in the Checkly account. Inline authentication, request details, environment variables, executable scripts, and URLs are excluded.",
        "docs_url": "https://api.checklyhq.com/openapi.json",
        "columns": {
            "id": "Unique check ID.",
            "name": "Check name.",
            "checkType": "Type of monitoring check.",
            "groupId": "ID of the group that contains the check.",
            "created_at": "Time when the check was created.",
        },
    },
    "check_groups": {
        "description": "Groups that share settings across monitoring checks. Inline authentication, request details, environment variables, executable scripts, and URLs are excluded.",
        "docs_url": "https://api.checklyhq.com/openapi.json",
        "columns": {"id": "Unique group ID.", "name": "Group name."},
    },
    "alert_channels": {
        "description": "Configured alert channels and their subscribed checks. Secret-bearing channel configuration is excluded.",
        "docs_url": "https://api.checklyhq.com/openapi.json",
        "columns": {
            "id": "Unique alert channel ID.",
            "type": "Alert channel type.",
            "created_at": "Time when the alert channel was created.",
        },
    },
    "check_statuses": {
        "description": "Current status of each check, updated as results arrive.",
        "docs_url": "https://api.checklyhq.com/openapi.json",
        "columns": {
            "checkId": "ID of the check for this status.",
            "hasFailures": "Whether the check is currently failing.",
            "hasErrors": "Whether a Checkly error caused the check to fail.",
            "lastRunLocation": "Location of the latest run.",
        },
    },
    "check_results": {
        "description": "Individual check runs, including final results and retry attempts, within the available 30-day history.",
        "docs_url": "https://api.checklyhq.com/openapi.json",
        "columns": {
            "id": "Unique result ID.",
            "checkId": "ID of the check that produced the result.",
            "created_at": "Time when the result was created.",
            "hasFailures": "Whether the run had a failure.",
            "hasErrors": "Whether an internal Checkly error occurred.",
            "runLocation": "Data center where the check ran.",
            "responseTime": "Time to produce the result, in milliseconds.",
            "resultType": "Whether this result is final or a retry attempt.",
        },
    },
    "locations": {
        "description": "Public Checkly data center locations, used to resolve run location region codes to readable names.",
        "docs_url": "https://api.checklyhq.com/openapi.json",
        "columns": {"region": "Unique region code of the location.", "name": "Readable name of the location."},
    },
    "private_locations": {
        "description": "Private locations that run checks on agents hosted by the account. Agent keys and proxy URLs are excluded.",
        "docs_url": "https://api.checklyhq.com/openapi.json",
        "columns": {
            "id": "Unique private location ID.",
            "name": "Name of the private location.",
            "slugName": "Slug used to reference the private location in run locations.",
            "created_at": "Time when the private location was created.",
            "lastSeen": "Time when an agent of the private location last reported.",
            "agentCount": "Number of agents connected to the private location.",
            "minAgentVersion": "Lowest agent version connected to the private location.",
        },
    },
    "error_groups": {
        "description": "Recurring check errors grouped by their cleaned error message. Raw error messages and root cause analyses are excluded.",
        "docs_url": "https://api.checklyhq.com/openapi.json",
        "columns": {
            "id": "Unique error group ID.",
            "checkId": "ID of the check that produced the errors.",
            "errorHash": "Hash of the cleaned error message, used to group errors.",
            "cleanedErrorMessage": "Sanitized error message used for grouping.",
            "firstSeen": "Time when the error was first seen.",
            "lastSeen": "Time when the error was last seen.",
            "archivedUntilNextEvent": "Whether the group is archived until the error occurs again.",
        },
    },
}
