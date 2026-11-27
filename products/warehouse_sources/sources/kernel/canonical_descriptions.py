from products.warehouse_sources.sources.sdk import CanonicalDescriptions

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
    "auth_connections": {
        "description": "A managed auth connection that keeps a browser profile signed in to one website domain. Hosted login and live view URLs are not synced.",
        "docs_url": "https://kernel.sh/docs/api-reference/managed-auth/list-auth-connections",
        "columns": {
            "id": "Unique identifier for the auth connection.",
            "profile_name": "Name of the profile associated with this auth connection.",
            "domain": "Target domain for authentication.",
            "status": "Last known authentication status of the managed profile.",
            "save_credentials": "Whether credentials are saved after every successful login.",
            "record_session": "Whether browser session replays are recorded for this connection by default.",
            "health_checks": "Whether periodic health checks are enabled for this connection.",
            "health_check_interval": "Interval in seconds between automatic health checks.",
            "last_auth_check_at": "When the most recent auth health check ran for this connection, regardless of outcome.",
            "auto_reauth": "Whether automatic re-authentication is permitted for this connection.",
            "can_reauth": "Whether the stored requirements of this connection are eligible for unattended re-authentication.",
            "flow_status": "Status of the login flow in progress, or null when no flow is in progress.",
            "flow_type": "Type of the login flow in progress, or null when no flow is in progress.",
            "error_code": "Machine-readable error code when the flow failed.",
            "error_message": "Error message when the flow failed.",
        },
    },
    "auth_connection_events": {
        "description": "A login, automatic reauth, or health check event in the timeline of a managed auth connection.",
        "docs_url": "https://kernel.sh/docs/api-reference/managed-auth/get-auth-connection-event-timeline",
        "columns": {
            "auth_connection_id": "ID of the auth connection that the event belongs to.",
            "id": "Identifier of the underlying login or reauth session, or of the health check.",
            "type": "Kind of event: login, reauth, or health_check.",
            "timestamp": "When the event occurred.",
            "status": "Outcome of the event. For login and reauth events this is the flow status.",
            "previous_status": "Session state observed before a health check event, when recorded.",
            "step": "Step that a login or reauth flow reached.",
            "error_code": "Machine-readable error code when a login or reauth event failed.",
            "error_message": "Human-readable error message when a login or reauth event failed.",
            "website_error": "Visible error message from the website, if the website displayed one.",
            "browser_session_id": "Browser session that produced the event, if one was created.",
            "replay_id": "Replay recording ID for the browser session of the event, if session recording was enabled.",
            "completed_at": "When the login or reauth attempt first reached a terminal status.",
            "updated_at": "When the login or reauth event was last updated.",
        },
    },
    "browser_replays": {
        "description": "A video replay recording of a browser session. Replay view URLs are not synced.",
        "docs_url": "https://kernel.sh/docs/api-reference/browser-replays/list-browser-session-replays",
        "columns": {
            "browser_session_id": "ID of the browser session that was recorded.",
            "replay_id": "Unique identifier for the replay recording.",
            "started_at": "Timestamp when the replay started.",
            "finished_at": "Timestamp when the replay finished.",
        },
    },
}
