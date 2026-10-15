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
    "Repositories": {
        "description": "A code repository connected to Waydev from a Git provider, including repositories "
        "that are not selected for processing.",
        "docs_url": "https://api-docs.waydev.co/returns-information-about-the-repositories-in-your-account",
        "columns": {
            "id": "Unique identifier of the repository in Waydev.",
            "name": "Short name of the repository.",
            "full_name": "Full name of the repository, including its owner or namespace.",
            "html_url": "URL of the repository at its Git provider.",
            "is_selected": "Whether the repository is selected for processing in Waydev.",
            "provider": "Git provider that hosts the repository, such as GitHub.",
        },
    },
    "Contributors": {
        "description": "A contributor (developer identity) known to Waydev from a connected integration.",
        "docs_url": "https://api-docs.waydev.co/list-contributors-in-your-account",
        "columns": {
            "id": "Unique identifier of the contributor.",
            "email": "Email address of the contributor.",
            "official_name": "Name of the contributor in Waydev.",
            "teams": "Teams the contributor belongs to.",
            "integration": "Integration the contributor comes from, such as Jira or GitLab.",
            "merged_developers": "Other developer identities merged into this contributor.",
        },
    },
    "Teams": {
        "description": "A team of developers defined in Waydev, used to group engineering metrics.",
        "docs_url": "https://api-docs.waydev.co/retrieves-all-the-teams-in-your-account",
        "columns": {
            "id": "Unique identifier of the team.",
            "name": "Name of the team.",
            "members_count": "Number of members in the team.",
            "members": "Members of the team, with their names and email addresses.",
            "settings": "Team settings that change how metrics are computed, such as merge and "
            "lines-of-code exclusions and the stats time zone.",
        },
    },
}
