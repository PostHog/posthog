"""Canonical, documentation-sourced descriptions for Aircall endpoints and columns.

Sourced from the official Aircall Public API reference (https://developer.aircall.io/api-references/).
Keyed by the endpoint names in `settings.py` `AIRCALL_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Aircall table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "calls": {
        "description": "A phone call handled through Aircall, inbound or outbound, with its participants and outcome.",
        "docs_url": "https://developer.aircall.io/api-references/#call",
        "columns": {
            "id": "Unique identifier for the call.",
            "direction": "Direction of the call: inbound or outbound.",
            "status": "Current status of the call (e.g. initial, answered, done).",
            "started_at": "Time the call started, as a UNIX timestamp.",
            "answered_at": "Time the call was answered, as a UNIX timestamp, if answered.",
            "ended_at": "Time the call ended, as a UNIX timestamp.",
            "duration": "Total duration of the call in seconds.",
            "raw_digits": "Phone number of the external party in raw international format.",
            "missed_call_reason": "Reason the call was missed, if it was not answered.",
            "user": "The Aircall user who handled the call.",
            "number": "The Aircall number the call came through.",
            "contact": "The contact associated with the external party, if matched.",
            "assigned_to": "The user the call was assigned to.",
            "recording": "URL of the call recording, if available.",
            "voicemail": "URL of the voicemail recording, if the call went to voicemail.",
            "cost": "Cost of the call.",
        },
    },
    "contacts": {
        "description": "A contact in the Aircall address book, with phone numbers and emails.",
        "docs_url": "https://developer.aircall.io/api-references/#contact",
        "columns": {
            "id": "Unique identifier for the contact.",
            "first_name": "Contact's first name.",
            "last_name": "Contact's last name.",
            "company_name": "Company the contact is associated with.",
            "information": "Free-form notes attached to the contact.",
            "is_shared": "Whether the contact is shared across the company.",
            "created_at": "Time the contact was created, as a UNIX timestamp.",
            "updated_at": "Time the contact was last updated, as a UNIX timestamp.",
            "phone_numbers": "List of phone numbers associated with the contact.",
            "emails": "List of email addresses associated with the contact.",
        },
    },
    "users": {
        "description": "An Aircall user (agent) who can make and receive calls in the account.",
        "docs_url": "https://developer.aircall.io/api-references/#user",
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "Full name of the user.",
            "email": "Email address of the user.",
            "available": "Whether the user is currently available to take calls.",
            "availability_status": "Detailed availability status of the user.",
            "created_at": "Time the user was created, as a UNIX timestamp.",
            "time_zone": "Time zone configured for the user.",
            "language": "Language configured for the user.",
            "state": "Account state of the user (e.g. active, deleted).",
        },
    },
    "teams": {
        "description": "A team of Aircall users that calls and numbers can be routed to.",
        "docs_url": "https://developer.aircall.io/api-references/#team",
        "columns": {
            "id": "Unique identifier for the team.",
            "name": "Name of the team.",
            "created_at": "Time the team was created, as a UNIX timestamp.",
            "users": "List of users that belong to the team.",
        },
    },
    "numbers": {
        "description": "An Aircall phone number that receives and places calls, with its routing settings.",
        "docs_url": "https://developer.aircall.io/api-references/#number",
        "columns": {
            "id": "Unique identifier for the number.",
            "name": "Display name of the number.",
            "digits": "The phone number in international format.",
            "country": "Two-letter ISO country code of the number.",
            "time_zone": "Time zone configured for the number.",
            "open": "Whether the number is currently open (within business hours).",
            "availability_status": "Current availability status of the number.",
            "is_ivr": "Whether the number uses an interactive voice response menu.",
            "created_at": "Time the number was created, as a UNIX timestamp.",
            "users": "List of users assigned to the number.",
        },
    },
    "tags": {
        "description": "A label that can be applied to calls in Aircall to categorize them.",
        "docs_url": "https://developer.aircall.io/api-references/#tag",
        "columns": {
            "id": "Unique identifier for the tag.",
            "name": "Name of the tag.",
            "color": "Color of the tag, as a hex value.",
            "description": "Description of what the tag is used for.",
        },
    },
}
