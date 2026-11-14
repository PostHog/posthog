"""Canonical, documentation-sourced descriptions for UserVoice Admin API v2 endpoints and columns.

Sourced from the official UserVoice Admin API v2 reference (https://developer.uservoice.com/docs/api/v2/reference/).
Keyed by the resource names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced UserVoice table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

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
    "supporters": {
        "description": "A user's support (vote) for a suggestion. `links.suggestion` and `links.user` join it to the suggestions and users tables.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            channel="Channel through which the support was given.",
            how="How the support was captured.",
            importance_score="Importance the supporter gave to the suggestion.",
            is_subscribed="Whether the supporter receives updates on the suggestion.",
            comments_count="Number of comments the supporter left on the suggestion.",
            requests_count="Number of feedback requests attached to this support.",
        ),
    },
    "features": {
        "description": "A roadmap feature that groups related suggestions. `links.suggestions` lists the suggestions it rolls up.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            name="Name of the feature.",
            description="Description of the feature.",
            position="Sort position of the feature.",
            suggestions_count="Number of suggestions linked to the feature.",
            supporting_users_count="Number of users who support the linked suggestions.",
            supporting_accounts_count="Number of accounts that support the linked suggestions.",
            supporter_revenue="Total revenue of the supporting accounts.",
            supporter_mrr_cents="Total monthly recurring revenue of the supporting accounts, in cents.",
        ),
    },
    "categories": {
        "description": "A category inside a forum that suggestions are filed under.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            name="Name of the category.",
            position="Sort position of the category in its forum.",
            suggestions_count="Number of suggestions in the category.",
            open_suggestions_count="Number of open suggestions in the category.",
        ),
    },
    "status_updates": {
        "description": "A status change on a suggestion and the message sent to its supporters. `links.old_status` and `links.new_status` give the transition.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            body="Text of the status update message.",
            html_body="HTML body of the status update message.",
            supporters_notified="Whether the suggestion's supporters were notified.",
            mail_sent_count="Number of notification emails sent.",
            mail_opened_count="Number of notification emails opened.",
            mail_clicked_count="Number of notification emails clicked.",
        ),
    },
}
