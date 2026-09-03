"""Canonical, documentation-sourced descriptions for Waydev endpoints and columns.

Sourced from the official Waydev API reference (https://api-docs.waydev.co). Keyed by the
resource names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Waydev table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Metrics": {
        "description": "The catalog of engineering metrics Waydev can report on for your account, such as "
        "impact, code churn, active days, and efficiency.",
        "docs_url": "https://api-docs.waydev.co/",
        "columns": {
            "id": "Metric identifier, used elsewhere as the metric key.",
            "name": "Human-readable name of the metric.",
            "unit": "Unit the metric is measured in.",
            "description": "HTML-formatted description of what the metric measures.",
        },
    },
    "Incidents": {
        "description": "An incident logged against a repository in Waydev, used to compute "
        "DORA metrics such as change failure rate and mean time to recovery.",
        "docs_url": "https://api-docs.waydev.co/retrieves-all-the-incidents-in-your-account",
        "columns": {
            "id": "Unique identifier of the incident.",
            "developer_id": "Identifier of the developer associated with the incident.",
            "repository_id": "Identifier of the repository the incident was logged against.",
            "number": "Reference number of the incident.",
            "title": "Title of the incident.",
            "url": "URL to the incident in its source system.",
            "issued_at": "Date and time the incident was raised.",
            "fixed_at": "Date and time the incident was marked as resolved, if any.",
        },
    },
}
