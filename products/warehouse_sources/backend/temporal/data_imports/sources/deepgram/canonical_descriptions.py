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
    "models": {
        "description": "A model the project can call, public or non-public, with the identifier that "
        "request rows refer to. Speech-to-text and text-to-speech models share the table and are told "
        "apart by `model_type`.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project_id": "Identifier of the project the model is available to.",
            "uuid": "Unique identifier for the model, as carried on request rows.",
            "model_type": "Whether the model came from the speech-to-text (stt) or text-to-speech (tts) catalogue.",
            "name": "The model's short name, for example nova-3.",
            "canonical_name": "The fully qualified model name used when calling the API.",
            "architecture": "The model family the model belongs to.",
            "languages": "IETF language tags the model supports.",
            "version": "Version identifier of the model.",
            "batch": "Whether the model can be used for batch (pre-recorded) speech-to-text.",
            "streaming": "Whether the model can be used for streaming speech-to-text.",
            "formatted_output": "Whether the model can return formatted output.",
            "metadata": "Voice metadata for a text-to-speech model, such as accent, age and sample audio.",
        },
    },
    "usage_breakdown": {
        "description": "Usage totals for one period of a project, broken down by the dimensions the "
        "request grouped on. Synced incrementally on the period's start date.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project_id": "Identifier of the project the usage belongs to.",
            "start": "First day of the period the row covers.",
            "end": "Last day of the period the row covers.",
            "grouping_key": "The dimension values this row aggregates, joined into one value. Empty when the row covers a whole period rather than a slice of it.",
            "hours": "Audio hours processed.",
            "total_hours": "Total hours including all processing.",
            "agent_hours": "Agent hours used.",
            "tokens_in": "Number of input tokens.",
            "tokens_out": "Number of output tokens.",
            "tts_characters": "Number of text-to-speech characters processed.",
            "requests": "Number of requests.",
            "accessor": "The accessor the usage is attributed to, when grouped by accessor.",
            "endpoint": "The API endpoint the usage came from, when grouped by endpoint.",
            "feature_set": "The set of features used, when grouped by feature set.",
            "models": "The models used, when grouped by model.",
            "method": "The processing method used, when grouped by method.",
            "tags": "The tags the requests carried, when grouped by tags.",
            "deployment": "The deployment the usage ran on, when grouped by deployment.",
        },
    },
    "billing_breakdown": {
        "description": "What a project was billed for one period, broken down by the dimensions the "
        "request grouped on. Synced incrementally on the period's start date.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project_id": "Identifier of the project the spend belongs to.",
            "start": "First day of the period the row covers.",
            "end": "Last day of the period the row covers.",
            "grouping_key": "The dimension values this row aggregates, joined into one value. Empty when the row covers a whole period rather than a slice of it.",
            "dollars": "Cost in US dollars for the row's period and grouping.",
            "accessor": "The accessor the spend is attributed to, when grouped by accessor.",
            "deployment": "The deployment the spend ran on, when grouped by deployment.",
            "line_item": "The billed line item, for example streaming::nova-3, when grouped by line item.",
            "tags": "The tags the billed requests carried, when grouped by tags.",
        },
    },
    "usage_fields": {
        "description": "The models, tags, processing methods and features the project used in the "
        "period. These are the dimensions a usage breakdown can be sliced by. One row per value.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project_id": "Identifier of the project the value was seen in.",
            "field": "Which set the value belongs to: models, tags, processing_methods or features.",
            "value": "The value itself. For a model this is the model identifier.",
            "name": "The model's name. Only set for a model row.",
            "language": "The IETF language tag the model supports. Only set for a model row.",
            "version": "Version identifier of the model. Only set for a model row.",
        },
    },
    "billing_fields": {
        "description": "The accessors, deployments, tags and line items the project was billed on in "
        "the period. These are the dimensions a billing breakdown can be sliced by. One row per value.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project_id": "Identifier of the project the value was seen in.",
            "field": "Which set the value belongs to: accessors, deployments, tags or line_items.",
            "value": "The value itself. For a line item this is the line item name.",
            "description": "The human-readable description of the line item. Only set for a line item row.",
        },
    },
}
