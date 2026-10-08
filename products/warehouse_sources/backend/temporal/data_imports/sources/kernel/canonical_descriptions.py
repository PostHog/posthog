from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Table-level descriptions are sourced from Kernel's public API docs. Column coverage is kept to the
# fields we're confident about (ids); the rest fall back to LLM enrichment, since the full column set
# was not verified against a live API for this alpha release.
_DOCS_URL = "https://docs.onkernel.com"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "apps": {
        "description": "A deployed browser-automation app registered in your Kernel organization.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the app.",
        },
    },
    "deployments": {
        "description": "A deployment of a Kernel app, including its status and region.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the deployment.",
        },
    },
    "invocations": {
        "description": "A single action run, including its status, input payload, output, and start/finish timestamps.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the invocation.",
        },
    },
    "browsers": {
        "description": "A cloud browser session run on Kernel infrastructure. Includes active and soft-deleted sessions.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the browser session.",
        },
    },
    "profiles": {
        "description": "A saved browser profile persisting cookies, storage, and authentication state across sessions.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the profile.",
        },
    },
    "browser_telemetry_events": {
        "description": "A telemetry event captured inside a browser session, such as a console message, network request, page navigation, or crash. Request and response headers and bodies, and screenshot images, are not synced.",
        "docs_url": "https://kernel.sh/docs/api-reference/browser-telemetry/read-telemetry-events-for-a-browser-session",
        "columns": {
            "browser_session_id": "ID of the browser session that captured the event.",
            "seq": "Sequence number assigned by the browser VM, increasing within a session.",
            "ts": "Event timestamp in Unix microseconds.",
            "category": "Event category, such as console, network, page, interaction, control, or system.",
            "type": "Event type, such as console_log, network_request, page_navigation, or page_crashed.",
            "data": "Event-specific payload. Its fields depend on the event type.",
            "source": "Provenance of the event: the producer kind (cdp, kernel_api, extension, local_process), its event name, and producer metadata.",
            "truncated": "True if the data field was truncated due to size limits.",
        },
    },
    "browser_pools": {
        "description": "A pool of identically configured, pre-warmed browsers that sessions are acquired from and released back to.",
        "docs_url": "https://kernel.sh/docs/api-reference/browser-pools/list-browser-pools",
        "columns": {
            "id": "Unique identifier for the browser pool.",
            "name": "Browser pool name, if set.",
            "region": "Geographic region of the browser pool. Fixed once the pool is created.",
            "acquired_count": "Number of browsers currently acquired from the pool.",
            "available_count": "Number of browsers currently available in the pool.",
            "browser_pool_config": "Configuration used to create all browsers in this pool, including its size.",
            "profile_id": "Resolved profile ID the pool is attached to. Omitted when no profile is attached.",
            "extension_ids": "Resolved extension IDs attached to the pool, in configured load order.",
            "created_at": "Timestamp when the browser pool was created.",
        },
    },
    "proxies": {
        "description": "A proxy configuration for routing browser traffic, with its latest health check result.",
        "docs_url": "https://kernel.sh/docs/api-reference/proxies/list-proxies",
        "columns": {
            "id": "Unique identifier for the proxy.",
            "name": "Readable name of the proxy.",
            "type": "Proxy type: datacenter, isp, residential, mobile, or custom.",
            "protocol": "Protocol to use for the proxy connection.",
            "status": "Current health status of the proxy.",
            "ip_address": "IP address that the proxy uses when making requests.",
            "last_checked": "Timestamp of the last health check performed on this proxy.",
            "config": "Configuration specific to the proxy type, such as target country or custom host and port.",
            "bypass_hosts": "Hostnames that bypass the proxy and connect directly.",
        },
    },
    "projects": {
        "description": "A project that isolates resources and access within a Kernel organization.",
        "docs_url": "https://kernel.sh/docs/api-reference/projects/list-projects",
        "columns": {
            "id": "Unique project identifier.",
            "name": "Project name, unique within the organization.",
            "status": "Project status.",
            "created_at": "When the project was created.",
            "updated_at": "When the project was last updated.",
        },
    },
    "audit_logs": {
        "description": "An authenticated API request made against the Kernel organization, recorded in the audit log.",
        "docs_url": "https://kernel.sh/docs/api-reference/audit-logs/list-audit-logs",
        "columns": {
            "id": "Synthetic identifier derived from the record contents. Kernel does not return an id for audit records.",
            "timestamp": "UTC time when the request was received.",
            "auth_strategy": "Authentication strategy used for the request.",
            "user_id": "ID of the authenticated user, if any.",
            "email": "Email of the authenticated user at request time, if any.",
            "method": "HTTP method.",
            "path": "Request path.",
            "route": "Matched API route pattern, if available.",
            "status": "HTTP response status code.",
            "domain": "Request host.",
            "duration_ms": "Request duration in milliseconds.",
            "client_ip": "Client IP address.",
            "user_agent": "User agent header.",
        },
    },
}
