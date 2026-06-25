"""Canonical, documentation-sourced descriptions for Delighted endpoints and columns.

Sourced from the official Delighted API reference (https://app.delighted.com/docs/api). Keyed by the
endpoint names in `settings.py` `DELIGHTED_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Delighted table. Delighted timestamps are UNIX epoch seconds. Columns absent here fall back to
LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "survey_responses": {
        "description": "A customer's response to a Delighted survey, including the score and any comment.",
        "docs_url": "https://app.delighted.com/docs/api/listing-survey-responses",
        "columns": {
            "id": "Unique identifier for the survey response.",
            "person": "The person who submitted the response (may be null for anonymous eNPS).",
            "person_id": "Identifier of the person who submitted the response.",
            "survey_type": "Type of survey the response is for (e.g. nps, csat, ces, smileys).",
            "score": "The numeric score the respondent gave.",
            "comment": "Free-text comment left by the respondent.",
            "permalink": "URL to view the response in Delighted.",
            "created_at": "Time the response was created, as a Unix timestamp.",
            "updated_at": "Time the response was last updated, as a Unix timestamp.",
            "notes": "Internal notes added to the response.",
            "tags": "Tags applied to the response.",
            "additional_answers": "Answers to any additional survey questions.",
        },
    },
    "people": {
        "description": "A person in Delighted who can be surveyed, with contact details and metadata.",
        "docs_url": "https://app.delighted.com/docs/api/listing-people",
        "columns": {
            "id": "Unique identifier for the person.",
            "name": "The person's name.",
            "email": "The person's email address.",
            "phone_number": "The person's phone number.",
            "created_at": "Time the person was created, as a Unix timestamp.",
            "last_sent_at": "Time a survey was last sent to the person, as a Unix timestamp.",
            "last_responded_at": "Time the person last responded to a survey, as a Unix timestamp.",
        },
    },
    "unsubscribes": {
        "description": "A person who has unsubscribed from Delighted surveys.",
        "docs_url": "https://app.delighted.com/docs/api/listing-unsubscribes",
        "columns": {
            "person_id": "Identifier of the person who unsubscribed.",
            "email": "Email address of the person who unsubscribed.",
            "name": "Name of the person who unsubscribed.",
            "unsubscribed_at": "Time the person unsubscribed, as a Unix timestamp.",
        },
    },
    "bounces": {
        "description": "A person whose survey email bounced and could not be delivered.",
        "docs_url": "https://app.delighted.com/docs/api/listing-bounces",
        "columns": {
            "person_id": "Identifier of the person whose email bounced.",
            "email": "Email address that bounced.",
            "name": "Name of the person whose email bounced.",
            "bounced_at": "Time the email bounced, as a Unix timestamp.",
        },
    },
    "metrics": {
        "description": "A point-in-time snapshot of the account's aggregate survey metrics (e.g. NPS).",
        "docs_url": "https://app.delighted.com/docs/api/getting-metrics",
        "columns": {
            "nps": "Net Promoter Score for the period.",
            "promoter_count": "Number of promoter responses.",
            "promoter_percent": "Percentage of responses that were promoters.",
            "passive_count": "Number of passive responses.",
            "passive_percent": "Percentage of responses that were passives.",
            "detractor_count": "Number of detractor responses.",
            "detractor_percent": "Percentage of responses that were detractors.",
            "response_count": "Total number of responses in the period.",
        },
    },
}
