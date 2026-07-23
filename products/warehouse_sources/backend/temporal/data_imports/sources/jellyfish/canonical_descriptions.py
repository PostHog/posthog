"""Canonical descriptions for Jellyfish export endpoints.

Sourced from the official Jellyfish-AI/jellyfish-mcp wrapper's tool documentation
(https://github.com/Jellyfish-AI/jellyfish-mcp) — the full API reference lives behind the
Jellyfish app login, so column-level coverage is limited to fields documented there. Keyed by the
endpoint names in `settings.py` `JELLYFISH_ENDPOINTS`.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_WINDOW_COLUMNS = {
    "window_start_date": "First day of the calendar-month window this row was exported for (added by PostHog).",
    "window_end_date": "Last day of the calendar-month window this row was exported for (added by PostHog).",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "engineers": {
        "description": "Active allocatable people tracked in Jellyfish, as returned by the people export.",
        "docs_url": "https://github.com/Jellyfish-AI/jellyfish-mcp",
        "columns": {
            "id": "Unique Jellyfish identifier for the person.",
        },
    },
    "teams": {
        "description": "The Jellyfish team hierarchy (top-level teams and their children).",
        "docs_url": "https://github.com/Jellyfish-AI/jellyfish-mcp",
        "columns": {
            "id": "Unique Jellyfish identifier for the team.",
            "name": "Display name of the team.",
            "active": "Whether the team is currently active in Jellyfish.",
            "hierarchy_level": "Depth of the team in the Jellyfish team hierarchy (1 = top level).",
            "hierarchy_level_name": "Label of the team's hierarchy level as configured in Jellyfish.",
        },
    },
    "work_categories": {
        "description": "Work categories configured in Jellyfish for grouping delivery work.",
        "docs_url": "https://github.com/Jellyfish-AI/jellyfish-mcp",
        "columns": {
            "slug": "Stable identifier for the work category, used to query its contents.",
            "display_name": "Display name of the work category.",
        },
    },
    "allocations_by_person": {
        "description": "R&D allocation (FTE effort) per person for each calendar-month window.",
        "docs_url": "https://github.com/Jellyfish-AI/jellyfish-mcp",
        "columns": {**_WINDOW_COLUMNS},
    },
    "allocations_by_team": {
        "description": "R&D allocation (FTE effort) per top-level team for each calendar-month window.",
        "docs_url": "https://github.com/Jellyfish-AI/jellyfish-mcp",
        "columns": {**_WINDOW_COLUMNS},
    },
    "allocations_by_investment_category": {
        "description": "R&D allocation (FTE effort) per investment category for each calendar-month window.",
        "docs_url": "https://github.com/Jellyfish-AI/jellyfish-mcp",
        "columns": {**_WINDOW_COLUMNS},
    },
    "company_metrics": {
        "description": "Company-wide engineering metrics (delivery and DORA-style measures) for each calendar-month window.",
        "docs_url": "https://github.com/Jellyfish-AI/jellyfish-mcp",
        "columns": {**_WINDOW_COLUMNS},
    },
    "unlinked_pull_requests": {
        "description": "Pull requests Jellyfish could not link to an issue, for each calendar-month window.",
        "docs_url": "https://github.com/Jellyfish-AI/jellyfish-mcp",
        "columns": {**_WINDOW_COLUMNS},
    },
    "deliverables": {
        "description": "Deliverables (epics/projects) in each Jellyfish work category, with delivery status and effort.",
        "docs_url": "https://github.com/Jellyfish-AI/jellyfish-mcp",
        "columns": {
            "work_category_slug": "Slug of the work category this deliverable was exported from (added by PostHog).",
            "name": "Display name of the deliverable.",
            "source_issue_url": "URL of the source issue (e.g. Jira epic) backing the deliverable.",
            "activity_status": "Delivery activity status of the deliverable (e.g. completed, in progress).",
            "target_date": "Target completion date for the deliverable.",
            "teams": "Teams contributing to the deliverable.",
        },
    },
}
