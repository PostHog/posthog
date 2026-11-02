from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "calls": {
        "description": "Inbound and outbound calls, including transcripts, outcomes, collected data, and recording URLs.",
        "docs_url": "https://docs.telli.com/v1/endpoint/list-calls",
        "columns": {
            "call_id": "Unique call identifier.",
            "contact_id": "Identifier of the contact involved in the call.",
            "agent_id": "Identifier of the agent that handled the call.",
            "triggered_at": "Time the call was triggered, in Unix milliseconds.",
            "triggered_at_iso": "Time the call was triggered, in ISO 8601 format.",
            "transcript": "Plain text transcript of the conversation.",
            "call_outcome": "Structured outcome values extracted from the conversation.",
            "recording_url": "Recording URL, available when both parties consent to recording.",
        },
    },
    "contacts": {
        "description": "Contacts with their custom properties and auto dialer enrollment status.",
        "docs_url": "https://docs.telli.com/v2/endpoint/list-contacts",
        "columns": {
            "id": "Unique contact identifier.",
            "externalId": "Contact identifier in the connected external system.",
            "properties": "Typed custom property values attached to the contact.",
            "createdAt": "Time the contact was created.",
            "updatedAt": "Time the contact was last updated.",
        },
    },
    "agents": {
        "description": "Voice agent definitions available in the telli account.",
        "docs_url": "https://docs.telli.com/v2/endpoint/list-agents",
        "columns": {
            "id": "Unique agent identifier.",
            "title": "Agent title.",
            "language": "Agent language.",
            "createdAt": "Time the agent was created.",
        },
    },
    "contact_properties": {
        "description": "Definitions of contact properties, including types, labels, and selection options.",
        "docs_url": "https://docs.telli.com/v2/endpoint/list-contact-properties",
        "columns": {
            "key": "Property key, unique within the account.",
            "dataType": "Type of value the property accepts.",
            "source": "Whether the property comes from the system, a user, or an integration.",
            "createdAt": "Time the property definition was created.",
        },
    },
    "phone_numbers": {
        "description": "Active phone numbers associated with the telli account.",
        "docs_url": "https://docs.telli.com/v1/endpoint/list-phone-numbers",
        "columns": {
            "id": "Unique phone number identifier.",
            "phoneNumber": "Phone number in E.164 format.",
            "inOutboundPool": "Whether the number is available for outbound calls.",
            "createdAt": "Time the number was added to the account.",
        },
    },
}
