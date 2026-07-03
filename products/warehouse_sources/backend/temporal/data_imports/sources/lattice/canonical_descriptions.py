"""Canonical, documentation-sourced descriptions for Lattice endpoints and columns.

Sourced from the official Lattice Talent (Public) API reference (https://developers.lattice.com).
Keyed by the endpoint names in `settings.py` `LATTICE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Lattice table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Lattice objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "createdAt": "Time at which the object was created.",
    "updatedAt": "Time at which the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "users": {
        "description": "An employee or member of the Lattice organization.",
        "docs_url": "https://developers.lattice.com/reference/get-users",
        "columns": _columns(
            name="The user's full name.",
            email="The user's email address.",
            title="The user's job title.",
            department="The department the user belongs to.",
            manager="The user's manager.",
            status="The user's employment status (e.g. active, inactive).",
            startDate="The user's employment start date.",
        ),
    },
    "departments": {
        "description": "A department or team within the Lattice organization.",
        "docs_url": "https://developers.lattice.com/reference/get-departments",
        "columns": _columns(
            name="The department's name.",
            parent="The parent department, if this is a sub-department.",
        ),
    },
    "goals": {
        "description": "A goal or objective tracked in Lattice for an individual, team, or company.",
        "docs_url": "https://developers.lattice.com/reference/get-goals",
        "columns": _columns(
            name="The goal's name.",
            description="Description of the goal.",
            status="Current status of the goal (e.g. on track, at risk, completed).",
            progress="Completion progress of the goal.",
            owner="The user who owns the goal.",
            priority="Priority assigned to the goal.",
            dueDate="Date by which the goal should be completed.",
            startDate="Date the goal started.",
            completedAt="Time at which the goal was completed.",
        ),
    },
    "feedbacks": {
        "description": "A piece of feedback given between users in Lattice.",
        "docs_url": "https://developers.lattice.com/reference/get-feedbacks",
        "columns": _columns(
            sender="The user who gave the feedback.",
            recipient="The user who received the feedback.",
            body="The content of the feedback.",
            visibility="Who can see the feedback (e.g. public, private, manager).",
        ),
    },
    "review_cycles": {
        "description": "A performance review cycle in Lattice, with a set timeframe and participants.",
        "docs_url": "https://developers.lattice.com/reference/get-review-cycles",
        "columns": _columns(
            name="The review cycle's name.",
            status="Current status of the review cycle (e.g. active, closed).",
            startDate="Start date of the review cycle.",
            endDate="End date of the review cycle.",
        ),
    },
    "updates": {
        "description": "A status update posted by a user in Lattice, often tied to goals or check-ins.",
        "docs_url": "https://developers.lattice.com/reference/get-updates",
        "columns": _columns(
            user="The user who posted the update.",
            body="The content of the update.",
            goal="The goal the update relates to, if any.",
        ),
    },
}
