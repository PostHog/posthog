"""Canonical, documentation-sourced descriptions for AssemblyAI endpoints and columns.

Sourced from the official AssemblyAI API reference (https://www.assemblyai.com/docs/api-reference/transcripts/get).
Keyed by the endpoint names in `settings.py` `ASSEMBLYAI_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced AssemblyAI table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "transcripts": {
        "description": "A speech-to-text transcript produced by AssemblyAI, including the recognized text and any requested audio-intelligence results (summary, sentiment, entities, chapters, and more).",
        "docs_url": "https://www.assemblyai.com/docs/api-reference/transcripts/get",
        "columns": {
            "id": "Unique identifier for the transcript.",
            "status": "Processing status of the transcript: queued, processing, completed, or error.",
            "audio_url": "URL of the media file that was transcribed.",
            "text": "The full transcribed text of the audio.",
            "language_code": "The language of the audio (e.g. en_us), detected or specified at submission.",
            "language_detection": "Whether automatic language detection was enabled.",
            "confidence": "Overall confidence score of the transcription, between 0 and 1.",
            "audio_duration": "Duration of the source audio in seconds.",
            "words": "Per-word results with text, start/end timestamps, confidence, and speaker label.",
            "utterances": "Speaker-segmented utterances when speaker diarization is enabled.",
            "summary": "Generated summary of the audio when summarization is enabled.",
            "summary_type": "The formatting model used for the summary (e.g. bullets, paragraph).",
            "summary_model": "The summarization model used to produce the summary.",
            "sentiment_analysis_results": "Sentiment (positive/neutral/negative) per segment when sentiment analysis is enabled.",
            "entities": "Detected named entities (people, organizations, locations, etc.) when entity detection is enabled.",
            "chapters": "Auto-generated chapters with headlines and summaries when auto chapters is enabled.",
            "iab_categories_result": "IAB topic categories detected in the audio when topic detection is enabled.",
            "content_safety_labels": "Content moderation labels detected in the audio when content safety is enabled.",
            "auto_highlights_result": "Key phrases and their occurrences when auto highlights is enabled.",
            "speaker_labels": "Whether speaker diarization was enabled for this transcript.",
            "webhook_url": "The URL AssemblyAI called on completion of this transcript, if a webhook was configured.",
            "error": "Error message when status is error.",
        },
    },
}
