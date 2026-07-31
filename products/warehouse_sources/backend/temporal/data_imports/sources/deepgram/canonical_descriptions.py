"""Canonical, documentation-sourced descriptions for Deepgram Management API endpoints and columns.

Sourced from the official Deepgram Management API reference
(https://developers.deepgram.com/reference/management-api). Keyed by the endpoint names in
`settings.py` `DEEPGRAM_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced table.
Columns absent here fall back to LLM enrichment. Every fan-out row carries a `project_id` column
identifying the Deepgram project it belongs to.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://developers.deepgram.com/reference/management-api"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "A Deepgram project — the top-level container that owns members, API keys, "
        "balances, and requests.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project_id": "Unique identifier for the project.",
            "name": "The project's display name.",
        },
    },
    "members": {
        "description": "A user who is a member of the project, with their assigned scopes.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project_id": "Identifier of the project the member belongs to.",
            "member_id": "Unique identifier for the member.",
            "email": "The member's email address.",
            "first_name": "The member's first name.",
            "last_name": "The member's last name.",
            "scopes": "The access scopes granted to the member within the project.",
        },
    },
    "keys": {
        "description": "An API key belonging to the project. The nested key object is flattened onto "
        "the row root, alongside the member the key was created for.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project_id": "Identifier of the project the API key belongs to.",
            "api_key_id": "Unique identifier for the API key.",
            "comment": "The human-readable label given to the key.",
            "scopes": "The access scopes granted to the key.",
            "tags": "Tags associated with the key.",
            "created": "Time at which the key was created.",
            "member": "The member the key was issued to.",
        },
    },
    "balances": {
        "description": "A funding balance for the project, in the account's billing units.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project_id": "Identifier of the project the balance belongs to.",
            "balance_id": "Unique identifier for the balance.",
            "amount": "The remaining amount on the balance.",
            "units": "The units the balance is measured in (e.g. usd, hour).",
            "purchase_order_id": "Identifier of the purchase the balance came from.",
        },
    },
    "invites": {
        "description": "A pending invitation for a user to join the project.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project_id": "Identifier of the project the invite is for.",
            "email": "The email address the invitation was sent to.",
            "scope": "The scope the invited user will be granted on joining.",
        },
    },
    "requests": {
        "description": "A single inference request made against the project, with model/feature "
        "metadata, the response code, and the time it was created. Synced incrementally on `created`.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project_id": "Identifier of the project the request was made under.",
            "request_id": "Unique identifier for the request.",
            "created": "Time at which the request was created.",
            "path": "The API path the request was made to.",
            "api_key_id": "Identifier of the API key that made the request.",
            "response": "Metadata about the response, including its status code and details.",
            "callback": "Callback delivery metadata, when the request used a callback URL.",
        },
    },
}
