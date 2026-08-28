from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS = "https://developer.mixmax.com/reference"

# Curated from the public Mixmax API docs (https://developer.mixmax.com). Keyed by the schema/endpoint
# name from `settings.ENDPOINTS`. Partial coverage is fine — anything missing falls back to LLM
# enrichment. Mixmax objects are MongoDB documents, so the identifier column is `_id` everywhere
# except live feed rows, which use `uid`.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sequences": {
        "description": "Automated multi-step outreach sequences the API token's user can access.",
        "docs_url": f"{_DOCS}/sequences",
        "columns": {
            "_id": "Unique identifier for the sequence.",
            "name": "Human-readable name of the sequence.",
        },
    },
    "sequence_folders": {
        "description": "Folders used to organize sequences.",
        "docs_url": f"{_DOCS}/sequence-folders",
        "columns": {
            "_id": "Unique identifier for the sequence folder.",
            "name": "Name of the folder.",
        },
    },
    "messages": {
        "description": "Tracked email messages sent through Mixmax.",
        "docs_url": f"{_DOCS}/messages",
        "columns": {
            "_id": "Unique identifier for the message.",
            "subject": "Subject line of the message.",
        },
    },
    "rules": {
        "description": "Automation rules that trigger Mixmax actions.",
        "docs_url": f"{_DOCS}/rules",
        "columns": {"_id": "Unique identifier for the rule."},
    },
    "code_snippets": {
        "description": "Reusable code snippets injected into emails.",
        "docs_url": f"{_DOCS}/code-snippets",
        "columns": {"_id": "Unique identifier for the code snippet."},
    },
    "snippet_tags": {
        "description": "Tags used to categorize snippets.",
        "docs_url": f"{_DOCS}/snippet-tags",
        "columns": {
            "_id": "Unique identifier for the snippet tag.",
            "name": "Name of the tag.",
        },
    },
    "meeting_types": {
        "description": "Configured meeting/appointment types used for scheduling.",
        "docs_url": f"{_DOCS}/meeting-types",
        "columns": {"_id": "Unique identifier for the meeting type."},
    },
    "insights_reports": {
        "description": "Saved insights reports.",
        "docs_url": f"{_DOCS}/insights",
        "columns": {"_id": "Unique identifier for the report."},
    },
    "polls": {
        "description": "Polls embedded in Mixmax emails.",
        "docs_url": f"{_DOCS}/polls",
        "columns": {"_id": "Unique identifier for the poll."},
    },
    "file_requests": {
        "description": "File requests sent through Mixmax.",
        "docs_url": f"{_DOCS}/file-requests",
        "columns": {"_id": "Unique identifier for the file request."},
    },
    "live_feed": {
        "description": "Real-time email tracking events such as opens, clicks and downloads.",
        "docs_url": f"{_DOCS}/live-feed",
        "columns": {"uid": "Unique identifier for the live feed event."},
    },
    "appointment_links": {
        "description": "The authenticated user's appointment (scheduling) links.",
        "docs_url": f"{_DOCS}/appointment-links",
        "columns": {
            "_id": "Unique identifier for the appointment link.",
            "userId": "Identifier of the user the appointment links belong to.",
        },
    },
    "users": {
        "description": "The authenticated Mixmax user's profile.",
        "docs_url": f"{_DOCS}/users",
        "columns": {
            "_id": "Unique identifier for the user.",
            "email": "The user's email address.",
        },
    },
    "user_preferences": {
        "description": "The authenticated user's Mixmax preferences.",
        "docs_url": f"{_DOCS}/user-preferences",
        "columns": {"_id": "Unique identifier for the preferences document."},
    },
}
