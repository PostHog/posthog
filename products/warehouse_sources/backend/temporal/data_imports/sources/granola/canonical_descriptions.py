"""Canonical, documentation-sourced descriptions for Granola endpoints and columns.

Sourced from the official Granola API reference (https://docs.granola.ai/api-reference). Keyed by the
endpoint names in `settings.py` `GRANOLA_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Granola table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "notes": {
        "description": "A meeting note in Granola with its AI-generated summary and transcript.",
        "docs_url": "https://docs.granola.ai/api-reference/list-notes",
        "columns": {
            "id": "Unique identifier for the note.",
            "title": "Title of the meeting note.",
            "summary": "AI-generated summary of the meeting.",
            "transcript": "Transcript of the meeting.",
            "created_at": "Time at which the note was created.",
            "updated_at": "Time at which the note was last updated.",
            "folder_id": "ID of the folder the note belongs to, if any.",
        },
    },
    "folders": {
        "description": "A folder used to organize notes in Granola.",
        "docs_url": "https://docs.granola.ai/api-reference/list-folders",
        "columns": {
            "id": "Unique identifier for the folder.",
            "name": "Name of the folder.",
        },
    },
    "transcripts": {
        "description": "A single item of a meeting transcript in Granola, one row per spoken segment.",
        "docs_url": "https://docs.granola.ai/api-reference/get-transcript",
        "columns": {
            "note_id": "ID of the note the transcript belongs to.",
            "speaker": "Speaker of the segment: audio source, attribution (`me` or `them`), diarization label, and resolved name when known.",
            "text": "Text of the transcript segment.",
            "start_time": "Start time of the transcript segment.",
            "end_time": "End time of the transcript segment.",
        },
    },
}
