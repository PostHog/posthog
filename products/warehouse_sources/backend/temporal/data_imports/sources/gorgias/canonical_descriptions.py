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
    "custom_fields": {
        "description": "A custom field definition that can be set on tickets or customers.",
        "docs_url": "https://developers.gorgias.com/reference/the-customfield-object",
        "columns": _columns(
            object_type="Type of object the field applies to (Ticket or Customer).",
            label="Name of the field shown to agents.",
            description="Description of the field.",
            priority="Display order of the field.",
            required="Whether a value is required.",
            managed_type="Set when Gorgias manages the field (e.g. AI Intent), otherwise null.",
            definition="Data type and input settings of the field, such as dropdown choices.",
            external_id="ID of the field in a foreign system.",
            deactivated_datetime="Time at which the field was archived, if applicable.",
        ),
    },
    "voice_calls": {
        "description": "A phone call handled through a Gorgias voice integration.",
        "docs_url": "https://developers.gorgias.com/reference/the-voicecall-object",
        "columns": _columns(
            ticket_id="ID of the ticket the call is attached to.",
            customer_id="ID of the customer on the call.",
            integration_id="ID of the phone integration that handled the call.",
            direction="Direction of the call (inbound or outbound).",
            status="Status of the call.",
            duration="Duration of the call in seconds.",
            started_datetime="Time at which the call started.",
        ),
    },
    "ticket_tags": {
        "description": "One row per tag applied to a ticket, linking tickets to tags.",
        "docs_url": "https://developers.gorgias.com/reference/list-ticket-tags",
        "columns": {
            "ticket_id": "ID of the ticket.",
            "ticket_created_datetime": "Time at which the ticket was created.",
            "id": "ID of the tag. Joins to the tags table.",
            "name": "Name of the tag.",
            "decoration": "Color or styling of the tag.",
        },
    },
    "ticket_field_values": {
        "description": "One row per custom field value set on a ticket, including Gorgias-managed fields.",
        "docs_url": "https://developers.gorgias.com/reference/list-ticket-custom-fields",
        "columns": {
            "ticket_id": "ID of the ticket.",
            "ticket_created_datetime": "Time at which the ticket was created.",
            "field_id": "ID of the custom field. Joins to the custom_fields table.",
            "field": "Definition of the custom field.",
            "value": "Value of the field on the ticket, as text.",
            "prediction": "Value predicted by Gorgias for the field, if any.",
        },
    },
    "customer_field_values": {
        "description": "One row per custom field value set on a customer.",
        "docs_url": "https://developers.gorgias.com/reference/list-customer-custom-fields-values",
        "columns": {
            "customer_id": "ID of the customer.",
            "customer_created_datetime": "Time at which the customer was created.",
            "field_id": "ID of the custom field. Joins to the custom_fields table.",
            "field": "Definition of the custom field.",
            "value": "Value of the field on the customer, as text.",
        },
    },
    "events": {
        "description": "Audit log of actions in the Gorgias account, such as ticket status changes and assignments. Gorgias keeps the last 12 months.",
        "docs_url": "https://developers.gorgias.com/reference/the-event-object",
        "columns": {
            "id": "ID of the event.",
            "created_datetime": "Time at which the event was created.",
            "type": "Type of the event, e.g. ticket-created or ticket-closed.",
            "object_type": "Type of the object the event is about, e.g. Ticket or Customer.",
            "object_id": "ID of the object the event is about.",
            "user_id": "ID of the user who triggered the event. Empty when a rule or automation triggered it.",
            "context": "UUID shared by a sequence of events where one event triggered the next.",
            "data": "Key-value data attached to the event.",
            "uri": "API URI of the event.",
        },
    },
    "voice_call_events": {
        "description": "A state change during a voice call, such as ringing, answered, or transferred.",
        "docs_url": "https://developers.gorgias.com/reference/the-voicecallevent-object",
        "columns": {
            "id": "ID of the event.",
            "created_datetime": "Time at which the event was created.",
            "type": "Type of the voice call event.",
            "call_id": "ID of the call. Joins to the voice_calls table.",
            "account_id": "ID of the account the event belongs to.",
            "user_id": "ID of the agent related to the event.",
            "customer_id": "ID of the customer related to the event.",
            "meta": "Data attached to the event.",
        },
    },
    "voice_call_recordings": {
        "description": "A voicemail or call recording attached to a voice call.",
        "docs_url": "https://developers.gorgias.com/reference/the-voicecallrecording-object",
        "columns": {
            "id": "ID of the voicemail or call recording.",
            "created_datetime": "Time at which the recording was created.",
            "call_id": "ID of the call. Joins to the voice_calls table.",
            "external_id": "ID of the recording at the telephony provider.",
            "url": "Direct access URL of the recording.",
            "duration": "Duration of the recording in seconds.",
            "type": "Whether this is a voicemail or a call recording.",
            "deleted_datetime": "Time at which the recording was deleted, if deleted.",
            "deleted_by_user_id": "ID of the agent who deleted the recording, if deleted.",
            "error_code": "Reason the URL could not be provided.",
            "transcription_status": "Status of the recording's transcription.",
        },
    },
}
