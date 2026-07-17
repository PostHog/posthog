"""Canonical, documentation-sourced descriptions for Typeform endpoints and columns.

Sourced from the official Typeform Create/Responses API reference
(https://www.typeform.com/developers/). Keyed by the endpoint names in `settings.py`
`TYPEFORM_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced Typeform table.
Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "forms": {
        "description": "A Typeform form (survey/quiz) with its questions, theme, and settings.",
        "docs_url": "https://www.typeform.com/developers/create/reference/retrieve-forms/",
        "columns": {
            "id": "Unique identifier for the form.",
            "title": "The form's title.",
            "type": "The type of form (e.g. quiz or form).",
            "language": "The form's language code.",
            "fields": "List of questions/fields that make up the form.",
            "workspace": "Reference to the workspace the form belongs to.",
            "theme": "Reference to the theme applied to the form.",
            "settings": "The form's settings (e.g. progress bar, language, public visibility).",
            "created_at": "Time at which the form was created.",
            "last_updated_at": "Time at which the form was last updated.",
            "published_at": "Time at which the form was published.",
            "_links": "Links related to the form, including its display (fill-out) URL.",
        },
    },
    "responses": {
        "description": "A single submission to a Typeform form, including the answers given.",
        "docs_url": "https://www.typeform.com/developers/responses/reference/retrieve-responses/",
        "columns": {
            "form_id": "ID of the form this response was submitted to.",
            "token": "Unique token identifying the response within its form.",
            "response_id": "Unique identifier for the response.",
            "landed_at": "Time at which the respondent landed on the form.",
            "submitted_at": "Time at which the response was submitted.",
            "answers": "List of answers given by the respondent, one per answered field.",
            "metadata": "Metadata about the response (browser, platform, referer, user agent).",
            "hidden": "Values of any hidden fields passed in the form URL.",
            "calculated": "Calculated values for the response, such as the quiz score.",
            "variables": "Variables defined on the form and their values for this response.",
        },
    },
}
