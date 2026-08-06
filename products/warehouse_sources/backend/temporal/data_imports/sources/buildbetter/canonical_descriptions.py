"""Canonical, documentation-sourced descriptions for BuildBetter endpoints and columns.

Sourced from the BuildBetter GraphQL API (https://api.buildbetter.app/v1/graphql) and the fields
selected in `queries.py`. Keyed by the endpoint names in `settings.py` `BUILDBETTER_ENDPOINTS`,
which match the `ExternalDataSchema.name` of a synced BuildBetter table. Columns absent here fall
back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "interviews": {
        "description": "A recorded interview or call in BuildBetter, with transcript, summaries, and attendees.",
        "docs_url": "https://docs.buildbetter.app/",
        "columns": {
            "id": "Unique identifier of the interview.",
            "external_id": "Identifier of the interview in the source system it was imported from.",
            "name": "Name or title of the interview.",
            "original_name": "Original name of the interview before any renaming.",
            "short_summary": "Short AI-generated summary of the interview.",
            "summary": "Full AI-generated summary of the interview.",
            "transcript_summary": "Summary derived from the interview transcript.",
            "source": "Source the interview originated from (e.g. Zoom, Google Meet).",
            "interaction": "Type of interaction the interview represents.",
            "permission": "Access permission level for the interview.",
            "asset_url": "URL of the recorded audio or video asset.",
            "asset_duration_seconds": "Duration of the recording in seconds.",
            "asset_is_audio": "Whether the asset is audio-only.",
            "meeting_url": "URL of the meeting the interview was recorded from.",
            "started_at": "Time at which the interview started.",
            "completed_at": "Time at which the interview completed.",
            "recorded_at": "Time at which the interview was recorded.",
            "created_at": "Time at which the interview record was created.",
            "updated_at": "Time at which the interview record was last updated.",
            "deleted_at": "Time at which the interview was deleted, if applicable.",
            "transcript_status": "Processing status of the transcript.",
            "summary_state": "Processing state of the AI summaries.",
            "attendees": "People who attended the interview.",
            "tags": "Tags applied to the interview.",
        },
    },
    "extractions": {
        "description": "An AI-extracted insight from an interview — a quote with sentiment, topics, and context.",
        "docs_url": "https://docs.buildbetter.app/",
        "columns": {
            "id": "Unique identifier of the extraction.",
            "interview_id": "Identifier of the interview the extraction came from.",
            "summary": "Summary of the extracted insight.",
            "context": "Surrounding context for the extracted insight.",
            "sentiment": "Sentiment detected for the extraction.",
            "severity": "Severity assigned to the extraction.",
            "bias": "Bias detected for the extraction.",
            "start_sec": "Start time of the extraction within the recording, in seconds.",
            "end_sec": "End time of the extraction within the recording, in seconds.",
            "created_at": "Time at which the extraction was created.",
            "speaker": "Speaker associated with the extraction.",
            "exact_quote": "The exact quote the extraction is based on.",
            "types": "Insight types assigned to the extraction.",
            "topics": "Topics associated with the extraction.",
            "keywords": "Keywords associated with the extraction.",
        },
    },
    "persons": {
        "description": "A person tracked in BuildBetter — an interview participant or customer contact.",
        "docs_url": "https://docs.buildbetter.app/",
        "columns": {
            "id": "Unique identifier of the person.",
            "external_id": "Identifier of the person in the source system they were imported from.",
            "first_name": "First name of the person.",
            "last_name": "Last name of the person.",
            "email": "Email address of the person.",
            "title": "Job title of the person.",
            "department": "Department the person belongs to.",
            "source": "Source the person originated from.",
            "source_identifier": "Identifier of the person in the originating source.",
            "company_id": "Identifier of the company the person belongs to.",
            "company": "Company the person belongs to.",
            "persona_id": "Identifier of the persona assigned to the person.",
            "persona": "Persona assigned to the person.",
            "created_at": "Time at which the person record was created.",
            "updated_at": "Time at which the person record was last updated.",
        },
    },
    "companies": {
        "description": "A company tracked in BuildBetter, grouping the people associated with it.",
        "docs_url": "https://docs.buildbetter.app/",
        "columns": {
            "id": "Unique identifier of the company.",
            "name": "Name of the company.",
            "domain": "Primary web domain of the company.",
            "photo_url": "URL of the company's logo or photo.",
            "created_at": "Time at which the company record was created.",
            "updated_at": "Time at which the company record was last updated.",
        },
    },
}
