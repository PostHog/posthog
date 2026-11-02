"""Canonical, documentation-sourced descriptions for UserVoice Admin API v2 endpoints and columns.

Sourced from the official UserVoice Admin API v2 reference (https://developer.uservoice.com/docs/api/v2/reference/).
Keyed by the resource names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced UserVoice table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://developer.uservoice.com/docs/api/v2/reference/"

# Fields shared by most UserVoice objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "created_at": "Time at which the object was created (ISO 8601).",
    "updated_at": "Time at which the object was last updated (ISO 8601).",
    "links": "Related-resource identifiers for this object (associations UserVoice exposes for side-loading).",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "suggestions": {
        "description": "A feedback idea submitted to a forum, carrying its vote and supporter counts and current status.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            title="Title of the suggestion.",
            formatted_text="Body text of the suggestion.",
            state="Lifecycle state of the suggestion (e.g. published, closed).",
            vote_count="Number of votes the suggestion has received.",
            subscriber_count="Number of users subscribed to updates on the suggestion.",
            comments_count="Number of comments on the suggestion.",
            category_name="Name of the category the suggestion belongs to.",
            closed_at="Time at which the suggestion was closed, if any.",
        ),
    },
    "forums": {
        "description": "A feedback forum that groups suggestions, optionally scoped to a product or audience.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            name="Name of the forum.",
            suggestions_count="Number of suggestions in the forum.",
            private="Whether the forum is private.",
            welcome_message="Welcome message shown on the forum.",
        ),
    },
    "users": {
        "description": "An end user (contact) who submits, votes on, or comments on feedback.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            name="Display name of the user.",
            email="Email address of the user.",
            karma_score="Contribution/karma score for the user.",
            last_seen_at="Time the user was last active.",
        ),
    },
    "comments": {
        "description": "A comment left by a user on a suggestion.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            formatted_text="Body text of the comment.",
            votes="Number of votes on the comment.",
        ),
    },
    "notes": {
        "description": "An internal admin note attached to a user or contact record.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            text="Body text of the note.",
        ),
    },
    "nps_ratings": {
        "description": "A Net Promoter Score rating submitted by a user, with the optional follow-up comment.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            rating="The 0–10 NPS rating value.",
            comment="Optional free-text comment left with the rating.",
            rated_at="Time at which the rating was submitted.",
        ),
    },
    "tickets": {
        "description": "A helpdesk support ticket. Only present on accounts with the Helpdesk feature enabled.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            subject="Subject line of the ticket.",
            state="Current state of the ticket (e.g. open, closed).",
            priority="Priority assigned to the ticket.",
            assignee_name="Name of the admin the ticket is assigned to.",
        ),
    },
    "ticket_messages": {
        "description": "An individual message within a helpdesk ticket thread. Requires the Helpdesk feature.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            body="Body text of the message.",
            direction="Whether the message was inbound (from the user) or outbound (from an admin).",
        ),
    },
    "suggestion_statuses": {
        "description": "A configurable status label that can be applied to suggestions (e.g. planned, started, completed).",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            name="Name of the status.",
            hex_color="Display color for the status.",
        ),
    },
    "labels": {
        "description": "A label used to tag and organize suggestions.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            name="Name of the label.",
        ),
    },
}
