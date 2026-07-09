from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "Deepgram projects associated with the API key. Projects organize all Deepgram resources: users, API keys, billing, and usage.",
        "docs_url": "https://developers.deepgram.com/reference/manage/projects/list",
        "columns": {
            "project_id": "The unique identifier of the project.",
            "name": "The name of the project.",
        },
    },
    "api_keys": {
        "description": "API keys created in each Deepgram project, including their scopes and the member who created them.",
        "docs_url": "https://developers.deepgram.com/reference/manage/keys/list",
        "columns": {
            "project_id": "The unique identifier of the project the key belongs to.",
            "api_key_id": "The unique identifier of the API key.",
            "comment": "The comment (label) attached to the API key when it was created.",
            "scopes": "The scopes granted to the API key.",
            "created": "The date and time the API key was created.",
            "expiration_date": "The date and time the API key expires, if an expiration was set.",
            "member": "The member who created the API key ({member_id, email}).",
        },
    },
    "members": {
        "description": "Members of each Deepgram project and the scopes they hold.",
        "docs_url": "https://developers.deepgram.com/reference/manage/members/list",
        "columns": {
            "project_id": "The unique identifier of the project the member belongs to.",
            "member_id": "The unique identifier of the member.",
            "email": "The email address of the member.",
            "first_name": "The first name of the member.",
            "last_name": "The last name of the member.",
            "scopes": "The API scopes of the member.",
        },
    },
    "balances": {
        "description": "Outstanding prepaid credit balances for each Deepgram project.",
        "docs_url": "https://developers.deepgram.com/reference/manage/billing/list",
        "columns": {
            "project_id": "The unique identifier of the project the balance belongs to.",
            "balance_id": "The unique identifier of the balance.",
            "amount": "The amount of the balance.",
            "units": "The units of the balance, such as USD.",
            "purchase_order_id": "Description or reference of the purchase that created the balance.",
        },
    },
    "requests": {
        "description": "Per-request usage log for each Deepgram project: every transcription, text-to-speech, and voice-agent API request with its path, model/feature metadata, and response code.",
        "docs_url": "https://developers.deepgram.com/reference/manage/requests/list",
        "columns": {
            "project_id": "The unique identifier of the project the request was made against.",
            "request_id": "The unique identifier of the request.",
            "created": "The date and time the request was created.",
            "path": "The API path of the request.",
            "api_key_id": "The unique identifier of the API key that made the request.",
            "response": "The response of the request, including model and feature metadata.",
            "code": "The HTTP response code of the request.",
            "deployment": "The deployment type that served the request (hosted, beta, or self-hosted).",
        },
    },
}
