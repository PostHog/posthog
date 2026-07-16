from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_API_DOCS = "https://platform.openai.com/docs/api-reference"

_USAGE_DIMENSION_COLUMNS = {
    "id": "Synthesized surrogate key: a hash of the bucket start and every grouping dimension.",
    "start_time": "Start of the time bucket (inclusive) as a UTC timestamp.",
    "end_time": "End of the time bucket (exclusive) as a UTC timestamp.",
    "project_id": "ID of the project the usage is attributed to, or null.",
    "user_id": "ID of the user the usage is attributed to, or null.",
    "api_key_id": "ID of the API key used, or null.",
    "model": "Model used, or null.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "usage_completions": {
        "description": "Chat and text completions token usage aggregated into daily buckets, broken down by project, user, API key, model, batch, and service tier.",
        "docs_url": f"{_API_DOCS}/usage/completions",
        "columns": {
            **_USAGE_DIMENSION_COLUMNS,
            "batch": "Whether the usage came from the Batch API, or null.",
            "service_tier": "Service tier used, or null.",
            "input_tokens": "Aggregated number of text input tokens used, including cached tokens.",
            "input_cached_tokens": "Aggregated number of text input tokens that have been cached from previous requests.",
            "output_tokens": "Aggregated number of text output tokens used.",
            "input_audio_tokens": "Aggregated number of audio input tokens used.",
            "output_audio_tokens": "Aggregated number of audio output tokens used.",
            "num_model_requests": "Count of requests made to the model.",
        },
    },
    "usage_embeddings": {
        "description": "Embeddings token usage aggregated into daily buckets, broken down by project, user, API key, and model.",
        "docs_url": f"{_API_DOCS}/usage/embeddings",
        "columns": {
            **_USAGE_DIMENSION_COLUMNS,
            "input_tokens": "Aggregated number of input tokens used.",
            "num_model_requests": "Count of requests made to the model.",
        },
    },
    "usage_moderations": {
        "description": "Moderations token usage aggregated into daily buckets, broken down by project, user, API key, and model.",
        "docs_url": f"{_API_DOCS}/usage/moderations",
        "columns": {
            **_USAGE_DIMENSION_COLUMNS,
            "input_tokens": "Aggregated number of input tokens used.",
            "num_model_requests": "Count of requests made to the model.",
        },
    },
    "usage_images": {
        "description": "Image generation usage aggregated into daily buckets, broken down by project, user, API key, model, image size, and source.",
        "docs_url": f"{_API_DOCS}/usage/images",
        "columns": {
            **_USAGE_DIMENSION_COLUMNS,
            "size": "Image size (e.g. 1024x1024), or null.",
            "source": "Image operation: image.generation, image.edit, or image.variation, or null.",
            "images": "Number of images processed.",
            "num_model_requests": "Count of requests made to the model.",
        },
    },
    "usage_audio_speeches": {
        "description": "Text-to-speech usage aggregated into daily buckets, broken down by project, user, API key, and model.",
        "docs_url": f"{_API_DOCS}/usage/audio_speeches",
        "columns": {
            **_USAGE_DIMENSION_COLUMNS,
            "characters": "Number of characters processed.",
            "num_model_requests": "Count of requests made to the model.",
        },
    },
    "usage_audio_transcriptions": {
        "description": "Speech-to-text usage aggregated into daily buckets, broken down by project, user, API key, and model.",
        "docs_url": f"{_API_DOCS}/usage/audio_transcriptions",
        "columns": {
            **_USAGE_DIMENSION_COLUMNS,
            "seconds": "Number of seconds of audio processed.",
            "num_model_requests": "Count of requests made to the model.",
        },
    },
    "usage_vector_stores": {
        "description": "Vector store storage usage aggregated into daily buckets, broken down by project.",
        "docs_url": f"{_API_DOCS}/usage/vector_stores",
        "columns": {
            "id": "Synthesized surrogate key: a hash of the bucket start and every grouping dimension.",
            "start_time": "Start of the time bucket (inclusive) as a UTC timestamp.",
            "end_time": "End of the time bucket (exclusive) as a UTC timestamp.",
            "project_id": "ID of the project the usage is attributed to, or null.",
            "usage_bytes": "Vector store usage in bytes.",
        },
    },
    "usage_code_interpreter_sessions": {
        "description": "Code interpreter session usage aggregated into daily buckets, broken down by project.",
        "docs_url": f"{_API_DOCS}/usage/code_interpreter_sessions",
        "columns": {
            "id": "Synthesized surrogate key: a hash of the bucket start and every grouping dimension.",
            "start_time": "Start of the time bucket (inclusive) as a UTC timestamp.",
            "end_time": "End of the time bucket (exclusive) as a UTC timestamp.",
            "project_id": "ID of the project the usage is attributed to, or null.",
            "num_sessions": "Number of code interpreter sessions.",
        },
    },
    "costs": {
        "description": "Daily spend for your OpenAI organization, broken down by project, line item, and API key.",
        "docs_url": f"{_API_DOCS}/usage/costs",
        "columns": {
            "id": "Synthesized surrogate key: a hash of the bucket start and every grouping dimension.",
            "start_time": "Start of the time bucket (inclusive) as a UTC timestamp.",
            "end_time": "End of the time bucket (exclusive) as a UTC timestamp.",
            "project_id": "ID of the project the cost is attributed to, or null.",
            "line_item": "Line item the cost is grouped by (e.g. a model and token type), or null.",
            "api_key_id": "ID of the API key the cost is attributed to, or null.",
            "amount_value": "Numeric value of the cost.",
            "amount_currency": "Lowercase ISO-4217 currency code, e.g. usd.",
            "quantity": "Quantity of the line item, when grouped by line item.",
        },
    },
    "projects": {
        "description": "Projects in your OpenAI organization (includes archived projects).",
        "docs_url": f"{_API_DOCS}/projects/list",
        "columns": {
            "id": "Unique identifier for the project.",
            "object": 'Object type, always "organization.project".',
            "name": "Display name of the project.",
            "created_at": "Unix timestamp (seconds) of when the project was created.",
            "archived_at": "Unix timestamp (seconds) of when the project was archived, or null if active.",
            "status": "Project status: active or archived.",
        },
    },
    "users": {
        "description": "Members of your OpenAI organization.",
        "docs_url": f"{_API_DOCS}/users/list",
        "columns": {
            "id": "Unique identifier for the user.",
            "object": 'Object type, always "organization.user".',
            "name": "Display name of the user.",
            "email": "Email address of the user.",
            "role": "Organization role: owner or reader.",
            "added_at": "Unix timestamp (seconds) of when the user joined the organization.",
        },
    },
    "invites": {
        "description": "Pending and historical invitations to join your OpenAI organization.",
        "docs_url": f"{_API_DOCS}/invite/list",
        "columns": {
            "id": "Unique identifier for the invite.",
            "object": 'Object type, always "organization.invite".',
            "email": "Email address the invite was sent to.",
            "role": "Organization role the invited user will receive: owner or reader.",
            "status": "Invite status: accepted, expired, or pending.",
            "invited_at": "Unix timestamp (seconds) of when the invite was created.",
            "expires_at": "Unix timestamp (seconds) of when the invite expires.",
            "accepted_at": "Unix timestamp (seconds) of when the invite was accepted, or null.",
        },
    },
    "admin_api_keys": {
        "description": "Organization-level Admin API keys.",
        "docs_url": f"{_API_DOCS}/admin-api-keys/list",
        "columns": {
            "id": "Unique identifier for the Admin API key.",
            "name": "Display name of the key.",
            "redacted_value": "Partially redacted hint for the key value.",
            "created_at": "Unix timestamp (seconds) of when the key was created.",
            "last_used_at": "Unix timestamp (seconds) of when the key was last used, or null.",
            "owner_type": "Type of the key's owner (user or service_account).",
            "owner_id": "ID of the key's owner.",
            "owner_name": "Display name of the key's owner.",
        },
    },
    "project_users": {
        "description": "Membership rows mapping users to the projects they belong to, one row per (project, user).",
        "docs_url": f"{_API_DOCS}/project-users/list",
        "columns": {
            "project_id": "ID of the project the user is a member of.",
            "id": "Unique identifier for the user.",
            "name": "Display name of the user.",
            "email": "Email address of the user.",
            "role": "Project role: owner or member.",
            "added_at": "Unix timestamp (seconds) of when the user was added to the project.",
        },
    },
    "project_service_accounts": {
        "description": "Service accounts (bot users not tied to a person) in each project.",
        "docs_url": f"{_API_DOCS}/project-service-accounts/list",
        "columns": {
            "project_id": "ID of the project the service account belongs to.",
            "id": "Unique identifier for the service account.",
            "name": "Display name of the service account.",
            "role": "Project role: owner or member.",
            "created_at": "Unix timestamp (seconds) of when the service account was created.",
        },
    },
    "project_api_keys": {
        "description": "API keys provisioned in each project.",
        "docs_url": f"{_API_DOCS}/project-api-keys/list",
        "columns": {
            "project_id": "ID of the project the key belongs to.",
            "id": "Unique identifier for the API key.",
            "name": "Display name of the API key.",
            "redacted_value": "Partially redacted hint for the key value.",
            "created_at": "Unix timestamp (seconds) of when the key was created.",
            "last_used_at": "Unix timestamp (seconds) of when the key was last used, or null.",
            "owner_type": "Type of the key's owner (user or service_account).",
            "owner_id": "ID of the user or service account that owns the key.",
            "owner_name": "Display name of the key's owner.",
        },
    },
    "project_rate_limits": {
        "description": "Per-model rate limit configuration for each project.",
        "docs_url": f"{_API_DOCS}/project-rate-limits/list",
        "columns": {
            "project_id": "ID of the project the rate limit applies to.",
            "id": "Unique identifier for the rate limit, per model.",
            "model": "Model the rate limit applies to.",
            "max_requests_per_1_minute": "Maximum requests allowed per minute.",
            "max_tokens_per_1_minute": "Maximum tokens allowed per minute.",
        },
    },
    "audit_logs": {
        "description": "User actions and configuration changes within your OpenAI organization.",
        "docs_url": f"{_API_DOCS}/audit-logs/list",
        "columns": {
            "id": "Unique identifier for the audit log event.",
            "type": "Event type, e.g. project.created or api_key.deleted.",
            "effective_at": "UTC timestamp of when the event occurred.",
            "actor": "JSON object describing the actor that performed the action (user, API key, or session).",
            "event_data": "JSON object with event-type-specific details.",
        },
    },
}
