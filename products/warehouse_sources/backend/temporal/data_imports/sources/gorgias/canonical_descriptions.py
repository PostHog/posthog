"""Canonical, documentation-sourced descriptions for Gorgias endpoints and columns.

Sourced from the official Gorgias REST API reference (https://developers.gorgias.com/reference).
Keyed by the endpoint names in `settings.py` `GORGIAS_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Gorgias table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Gorgias objects.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "created_datetime": "Time at which the object was created.",
    "updated_datetime": "Time at which the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "tickets": {
        "description": "A customer support conversation in Gorgias, holding messages and metadata.",
        "docs_url": "https://developers.gorgias.com/reference/get-a-ticket",
        "columns": _columns(
            status="Status of the ticket (open, closed).",
            channel="Channel the ticket came through (e.g. email, chat, phone).",
            subject="Subject line of the ticket.",
            priority="Priority of the ticket.",
            customer="The customer the ticket is with.",
            assignee_user="The agent assigned to the ticket.",
            assignee_team="The team assigned to the ticket.",
            via="The channel the ticket was created through.",
            from_agent="Whether the ticket was created by an agent rather than the customer.",
            is_unread="Whether the ticket has unread messages.",
            opened_datetime="Time at which the ticket was opened.",
            closed_datetime="Time at which the ticket was closed.",
            last_message_datetime="Time of the most recent message on the ticket.",
            tags="Tags applied to the ticket.",
        ),
    },
    "messages": {
        "description": "An individual message within a ticket (inbound or outbound).",
        "docs_url": "https://developers.gorgias.com/reference/get-a-message",
        "columns": _columns(
            ticket_id="ID of the ticket this message belongs to.",
            channel="Channel the message was sent through.",
            via="The medium the message was sent via.",
            source="Sender and recipient details of the message.",
            sender="The author of the message.",
            subject="Subject line of the message.",
            body_text="Plain-text body of the message.",
            body_html="HTML body of the message.",
            from_agent="Whether the message was sent by an agent.",
            sent_datetime="Time at which the message was sent.",
        ),
    },
    "customers": {
        "description": "A customer (end user) who contacts support in Gorgias.",
        "docs_url": "https://developers.gorgias.com/reference/get-a-customer",
        "columns": _columns(
            name="Full name of the customer.",
            email="Primary email address of the customer.",
            firstname="First name of the customer.",
            lastname="Last name of the customer.",
            language="Preferred language of the customer.",
            timezone="Timezone of the customer.",
            channels="Contact channels associated with the customer.",
        ),
    },
    "users": {
        "description": "An internal Gorgias user (support agent or admin).",
        "docs_url": "https://developers.gorgias.com/reference/get-a-user",
        "columns": _columns(
            name="Full name of the user.",
            email="Email address of the user.",
            firstname="First name of the user.",
            lastname="Last name of the user.",
            role="Role of the user (e.g. agent, admin).",
            active="Whether the user account is active.",
        ),
    },
    "satisfaction_surveys": {
        "description": "A customer satisfaction (CSAT) survey response tied to a ticket.",
        "docs_url": "https://developers.gorgias.com/reference/get-a-satisfaction-survey",
        "columns": _columns(
            ticket_id="ID of the ticket the survey relates to.",
            customer_id="ID of the customer who responded.",
            score="Satisfaction score given by the customer.",
            body_text="Free-text feedback left by the customer.",
            scored_datetime="Time at which the survey was scored.",
            sent_datetime="Time at which the survey was sent.",
        ),
    },
    "macros": {
        "description": "A reusable canned response or action template used by agents.",
        "docs_url": "https://developers.gorgias.com/reference/get-a-macro",
        "columns": _columns(
            name="Name of the macro.",
            body_text="Plain-text body of the macro.",
            body_html="HTML body of the macro.",
            language="Language of the macro.",
            actions="Actions performed when the macro is applied.",
        ),
    },
    "tags": {
        "description": "A label that can be applied to tickets to categorize them.",
        "docs_url": "https://developers.gorgias.com/reference/get-a-tag",
        "columns": _columns(
            name="Name of the tag.",
            decoration="Color or styling of the tag.",
        ),
    },
    "views": {
        "description": "A saved, filtered view of tickets used to organize the agent workspace.",
        "docs_url": "https://developers.gorgias.com/reference/get-a-view",
        "columns": _columns(
            name="Name of the view.",
            category="Category the view belongs to.",
            type="Type of object the view lists (e.g. ticket).",
            shared="Whether the view is shared with other users.",
            deactivated_datetime="Time at which the view was deactivated, if applicable.",
        ),
    },
    "teams": {
        "description": "A team of agents in Gorgias used to route and assign tickets.",
        "docs_url": "https://developers.gorgias.com/reference/get-a-team",
        "columns": _columns(
            name="Name of the team.",
            decoration="Color or styling of the team.",
        ),
    },
}
