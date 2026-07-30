"""Canonical, documentation-sourced descriptions for AppSignal endpoints and columns.

Sourced from the official AppSignal API docs (https://docs.appsignal.com/api/) and the published
GraphQL schema reference (https://appsignal.com/graphql/docs). Keyed by the endpoint names in
`settings.py` `APPSIGNAL_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
AppSignal table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "exception_incidents": {
        "description": "An exception incident: a group of similar errors tracked by AppSignal, with its occurrence count and triage state.",
        "docs_url": "https://docs.appsignal.com/api/graphql/examples.html",
        "columns": {
            "id": "Unique identifier for the incident.",
            "number": "Human-facing incident number, unique within the app.",
            "count": "Total number of occurrences recorded for this incident.",
            "state": "Triage state of the incident: OPEN, CLOSED, or WIP.",
            "severity": "Severity assigned to the incident.",
            "namespace": "Namespace the incident occurred in (e.g. web, background).",
            "description": "Description of the incident.",
            "actionNames": "Actions (controller/job names) the incident occurred in.",
            "lastOccurredAt": "Time the incident last occurred.",
            "createdAt": "Time the incident was first created.",
            "updatedAt": "Time the incident was last updated.",
            "exceptionName": "Class name of the exception (e.g. NoMethodError).",
            "exceptionMessage": "Message of the most recent exception occurrence.",
            "firstBacktraceLine": "First line of the exception backtrace.",
            "errorGroupingStrategy": "Strategy AppSignal used to group errors into this incident.",
        },
    },
    "performance_incidents": {
        "description": "A performance incident: a slow action tracked by AppSignal, with its duration statistics and triage state.",
        "docs_url": "https://docs.appsignal.com/api/graphql/examples.html",
        "columns": {
            "id": "Unique identifier for the incident.",
            "number": "Human-facing incident number, unique within the app.",
            "count": "Total number of occurrences recorded for this incident.",
            "state": "Triage state of the incident: OPEN, CLOSED, or WIP.",
            "severity": "Severity assigned to the incident.",
            "namespace": "Namespace the incident occurred in (e.g. web, background).",
            "description": "Description of the incident.",
            "actionNames": "Actions (controller/job names) the incident occurred in.",
            "lastOccurredAt": "Time the incident last occurred.",
            "createdAt": "Time the incident was first created.",
            "updatedAt": "Time the incident was last updated.",
            "mean": "Mean duration of the action in milliseconds.",
            "totalDuration": "Total time spent in the action in milliseconds.",
            "hasNPlusOne": "Whether any of the last 5 deploys contained an N+1 query for this action.",
        },
    },
    "deploy_markers": {
        "description": "A deploy marker: an application release tracked by AppSignal, with the error rate observed while it was live.",
        "docs_url": "https://docs.appsignal.com/api/markers.html",
        "columns": {
            "id": "Unique identifier for the marker.",
            "created_at": "Time the deploy marker was created.",
            "closed_at": "Time the next deploy superseded this one; null while it is the live deploy.",
            "live_for": "Time this deploy was live, in seconds.",
            "live_for_in_words": "Human-readable version of the live duration (e.g. 1d).",
            "gem_version": "Version of the AppSignal integration that reported the deploy.",
            "repository": "Git repository reference for the deploy.",
            "revision": "Git revision of the deploy.",
            "short_revision": "Abbreviated git revision of the deploy.",
            "git_compare_url": "URL comparing this deploy's revision with the previous one.",
            "user": "User who triggered the deploy.",
            "exception_count": "Number of exceptions recorded while this deploy was live.",
            "exception_rate": "Exception rate observed while this deploy was live.",
        },
    },
    "error_samples": {
        "description": "An individual error sample: one recorded occurrence of an exception, with request context.",
        "docs_url": "https://docs.appsignal.com/api/samples.html",
        "columns": {
            "id": "Unique identifier for the sample.",
            "action": "Action (controller/job name) the sample was recorded in.",
            "path": "Request path of the sampled request.",
            "duration": "Duration of the request in milliseconds; null for error samples.",
            "status": "HTTP status code of the sampled request.",
            "time": "Time the sample was recorded, as a UNIX timestamp.",
            "is_exception": "Whether the sample is an error sample.",
            "exception": "Exception details: name, message, and backtrace.",
        },
    },
    "performance_samples": {
        "description": "An individual performance sample: one recorded slow request, with timing breakdown.",
        "docs_url": "https://docs.appsignal.com/api/samples.html",
        "columns": {
            "id": "Unique identifier for the sample.",
            "action": "Action (controller/job name) the sample was recorded in.",
            "path": "Request path of the sampled request.",
            "duration": "Duration of the request in milliseconds.",
            "status": "HTTP status code of the sampled request.",
            "time": "Time the sample was recorded, as a UNIX timestamp.",
            "is_exception": "Whether the sample is an error sample; null for performance samples.",
            "exception": "Exception details; null for performance samples.",
        },
    },
}
