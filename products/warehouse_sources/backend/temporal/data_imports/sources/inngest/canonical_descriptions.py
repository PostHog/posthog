from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the official Inngest REST API reference: https://api-docs.inngest.com
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "events": {
        "description": "An event received by Inngest, including its payload and receipt metadata.",
        "docs_url": "https://api-docs.inngest.com/v1/events/ListEvents",
        "columns": {
            "internal_id": "Unique ULID Inngest assigned to the event on receipt; used internally and by the API.",
            "accountID": "The Inngest account the event belongs to.",
            "environmentID": "The Inngest environment the event was received in.",
            "source": 'The origin of the event, e.g. "key" for an event key.',
            "sourceID": "The ID of the key used to deliver the event.",
            "received_at": "When the event was received by Inngest.",
            "id": "The optional `id` field specified in the event by the sender.",
            "name": "The `name` field specified in the event.",
            "data": "The `data` payload specified in the event.",
            "user": "The `user` field specified in the event.",
            "ts": "The `ts` (unix millisecond) timestamp specified in the event.",
            "v": "The `v` (version) field specified in the event.",
        },
    },
    "function_runs": {
        "description": "A function run triggered by an event, with its status, timing, and output.",
        "docs_url": "https://api-docs.inngest.com/v1/events/ListEventRuns",
        "columns": {
            "run_id": "The ID of the function run.",
            "run_started_at": "When the function run was scheduled.",
            "ended_at": "If the function has ended, the end time; null while the run is still Running.",
            "status": "The run status, e.g. Running, Completed, Failed, Cancelled.",
            "output": "Data returned from the function handler, JSON-encoded when not already a string.",
            "function_id": "The ID of the function that ran.",
            "function_version": "The version of the function that ran.",
            "environment_id": "The Inngest environment the run executed in.",
            "event_id": "The internal ID of the triggering event, if the run was initialized via a single event.",
            "batch_id": "The ID of the batch, if the run was initialized via a batch of events.",
            "original_run_id": "The run ID of the original run, if this run is a replay.",
            "cron": "The cron expression that scheduled the run, if it was initialized via a cron trigger.",
            "event_received_at": "When the triggering event was received by Inngest (added by PostHog to drive incremental sync).",
        },
    },
    "cancellations": {
        "description": "A bulk cancellation, stopping function runs in a time range matching an optional expression.",
        "docs_url": "https://api-docs.inngest.com/v1/cancellations/ListCancellations",
        "columns": {
            "id": "Unique identifier of the cancellation.",
            "environment_id": "The Inngest environment the cancellation applies to.",
            "function_internal_id": "Inngest's internal ID of the targeted function.",
            "function_id": "The ID (slug) of the targeted function.",
            "started_before": "Only runs started before this time are cancelled.",
            "started_after": "Only runs started after this time are cancelled.",
            "if": "Optional CEL expression limiting which runs are cancelled.",
        },
    },
    "environments": {
        "description": "An Inngest environment (production, test, or branch).",
        "docs_url": "https://api-docs.inngest.com/v2/environments/FetchAccountEnvs",
        "columns": {
            "id": "Unique identifier of the environment.",
            "name": "The environment name.",
            "type": "The environment type: PRODUCTION, TEST, or BRANCH.",
            "createdAt": "When the environment was created.",
            "isArchived": "Whether the environment has been archived.",
        },
    },
    "webhooks": {
        "description": "An inbound webhook intake endpoint that transforms third-party payloads into Inngest events. The secret intake URL is not synced.",
        "docs_url": "https://api-docs.inngest.com/v1/webhooks/ListWebhooks",
        "columns": {
            "id": "Unique identifier of the webhook endpoint.",
            "name": "A custom descriptor for the webhook endpoint.",
            "transform": "JavaScript transform turning the inbound request into an Inngest event payload.",
            "created_at": "When the webhook endpoint was created.",
            "updated_at": "When the webhook endpoint was last updated.",
        },
    },
    "event_keys": {
        "description": "An event key used to send events to Inngest. The secret key material is not synced.",
        "docs_url": "https://api-docs.inngest.com/v2/keys/FetchAccountEventKeys",
        "columns": {
            "id": "Unique identifier of the event key.",
            "name": "The event key's name.",
            "environment": "The environment the event key belongs to.",
            "createdAt": "When the event key was created.",
        },
    },
    "signing_keys": {
        "description": "A signing key used to authenticate Inngest API and SDK traffic. The secret key material is not synced.",
        "docs_url": "https://api-docs.inngest.com/v2/keys/FetchAccountSigningKeys",
        "columns": {
            "id": "Unique identifier of the signing key.",
            "name": "The signing key's name.",
            "environment": "The environment the signing key belongs to.",
            "createdAt": "When the signing key was created.",
        },
    },
}
