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
}
