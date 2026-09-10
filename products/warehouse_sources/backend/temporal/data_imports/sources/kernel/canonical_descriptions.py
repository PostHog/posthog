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
}
