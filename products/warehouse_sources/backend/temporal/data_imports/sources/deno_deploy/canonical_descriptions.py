"""Canonical, documentation-sourced descriptions for Deno Deploy endpoints and columns.

Sourced from the official Deno Deploy v2 API reference (https://docs.deno.com/deploy/api/ and the
OpenAPI spec at https://api.deno.com/v2/openapi.json). Keyed by the endpoint names in `settings.py`
`DENO_DEPLOY_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced table. Columns absent
here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "apps": {
        "description": "A Deno Deploy application: a web service that serves traffic within the organization, identified by a unique slug.",
        "docs_url": "https://docs.deno.com/deploy/reference/apps/",
        "columns": {
            "id": "Unique identifier (UUID) for the app.",
            "slug": "Human-readable slug, unique within the organization and used in default domain names.",
            "labels": "Key/value labels attached to the app.",
            "layers": "Shared configuration layers applied to the app.",
            "created_at": "Time at which the app was created.",
            "updated_at": "Time at which the app was last updated.",
        },
    },
    "revisions": {
        "description": "A single version (build) of an app's code. When deploying from GitHub, revisions generally map one-to-one to git commits.",
        "docs_url": "https://docs.deno.com/deploy/reference/builds/",
        "columns": {
            "id": "Unique identifier for the revision.",
            "app_id": "Identifier of the app this revision belongs to (added by PostHog when fanning out over apps).",
            "app_slug": "Slug of the app this revision belongs to (added by PostHog).",
            "status": "Current build/deployment status of the revision.",
            "failure_reason": "Why the build failed, if it did (error, cancelled, timed_out, or skipped).",
            "labels": "Key/value labels attached to the revision.",
            "created_at": "Time at which the revision was created.",
            "cancellation_requested_at": "Time at which cancellation was requested, if any.",
            "build_finished_at": "Time at which the build finished, if it has.",
            "deleted_at": "Time at which the revision was deleted, if it has been.",
        },
    },
    "domains": {
        "description": "A custom domain mapped to the organization's deployments, with its verification and TLS certificate state.",
        "docs_url": "https://docs.deno.com/deploy/reference/domains/",
        "columns": {
            "id": "Unique identifier for the domain.",
            "organization_id": "Identifier of the organization that owns the domain.",
            "domain": "The custom domain name (e.g. mycompany.com).",
            "kind": "The kind of domain mapping.",
            "verification_token": "Token used to verify ownership of the domain.",
            "is_validated": "Whether ownership of the domain has been validated.",
            "dns_records": "DNS records that must be configured for the domain.",
            "provisioning_status": "Status of TLS certificate provisioning for the domain.",
            "certificates": "TLS certificates provisioned or uploaded for the domain.",
            "created_at": "Time at which the domain was added.",
            "updated_at": "Time at which the domain was last updated.",
        },
    },
    "analytics": {
        "description": "Per-app usage metrics in 15-minute buckets (request count, CPU, bandwidth, KV units), reshaped from the columnar API response into one row per time bucket.",
        "docs_url": "https://docs.deno.com/deploy/api/",
        "columns": {
            "app_id": "Identifier of the app the metrics belong to (added by PostHog when fanning out over apps).",
            "app_slug": "Slug of the app the metrics belong to (added by PostHog).",
            "time": "Start of the 15-minute analytics bucket.",
            "request_count": "Number of requests served in the bucket.",
            "cpu_seconds": "CPU time consumed in the bucket, in seconds.",
            "runtime_seconds": "Wall-clock runtime in the bucket, in seconds.",
            "memory_time_byte_seconds": "Memory usage integrated over time (byte-seconds) in the bucket.",
            "network_ingress_bytes": "Inbound network bytes in the bucket.",
            "network_egress_bytes": "Outbound network bytes in the bucket.",
            "kv_read_units": "Deno KV read units consumed in the bucket.",
            "kv_write_units": "Deno KV write units consumed in the bucket.",
        },
    },
    "logs": {
        "description": "Runtime log lines emitted by an app over a time window. Each row is given a synthesized content-hash id since Deno Deploy runtime logs carry no natural identifier.",
        "docs_url": "https://docs.deno.com/deploy/api/",
        "columns": {
            "id": "Synthesized content-hash identifier (added by PostHog so log lines can be deduplicated on re-sync).",
            "app_id": "Identifier of the app that emitted the log (added by PostHog when fanning out over apps).",
            "app_slug": "Slug of the app that emitted the log (added by PostHog).",
            "timestamp": "Time at which the log line was emitted.",
            "level": "Severity level of the log line.",
            "message": "The log message text.",
            "revision_id": "Identifier of the revision that emitted the log.",
            "region": "Edge region the log was emitted from.",
            "trace_id": "Trace identifier for the request that emitted the log, if any.",
            "span_id": "Span identifier for the request that emitted the log, if any.",
        },
    },
}
