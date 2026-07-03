"""Canonical, documentation-sourced descriptions for Calendly endpoints and columns.

Sourced from the official Calendly v2 API reference (https://developer.calendly.com/api-docs).
Keyed by the endpoint names in `settings.py` `CALENDLY_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Calendly table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Calendly resources; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "uri": "Canonical resource reference (URI) that uniquely identifies the object.",
    "created_at": "Time at which the object was created.",
    "updated_at": "Time at which the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "event_types": {
        "description": "A Calendly event type — a configurable meeting that invitees can book.",
        "docs_url": "https://developer.calendly.com/api-docs/b3A6NTgxMjI2-list-user-s-event-types",
        "columns": _columns(
            name="Human-readable name of the event type.",
            active="Whether the event type is currently active and bookable.",
            slug="URL-friendly slug used in the event type's scheduling link.",
            scheduling_url="Public scheduling page URL for this event type.",
            duration="Length of the meeting in minutes.",
            duration_options="List of selectable meeting durations (in minutes) offered for the event type.",
            kind="Whether the event type is solo or group.",
            type="Whether the event type is a StandardEventType or AdhocEventType.",
            color="Hex color used for the event type in the Calendly UI.",
            description_plain="Plain-text description of the event type.",
            description_html="HTML description of the event type.",
            pooling_type="How invitees are assigned when the event type has multiple hosts.",
            secret="Whether the event type is hidden from the user's main scheduling page.",
            profile="Profile (user or team) that owns the event type.",
        ),
    },
    "scheduled_events": {
        "description": "A booked meeting (scheduled event) on a user's Calendly calendar.",
        "docs_url": "https://developer.calendly.com/api-docs/513b50a23c4dd-list-events",
        "columns": _columns(
            name="Name of the scheduled event.",
            status="Status of the event: active or canceled.",
            start_time="Scheduled start time of the meeting.",
            end_time="Scheduled end time of the meeting.",
            event_type="URI of the event type this meeting was booked from.",
            location="Location details for the meeting (in-person, video conference link, phone, etc.).",
            invitees_counter="Counts of total, active, and limit invitees for the event.",
            event_memberships="Hosts associated with the scheduled event.",
            cancellation="Cancellation details, present when the event has been canceled.",
            meeting_notes_plain="Plain-text meeting notes.",
            meeting_notes_html="HTML meeting notes.",
        ),
    },
    "groups": {
        "description": "A group within a Calendly organization used to organize members.",
        "docs_url": "https://developer.calendly.com/api-docs/c1957c0e1e44b-list-groups",
        "columns": _columns(
            name="Name of the group.",
            organization="URI of the organization the group belongs to.",
        ),
    },
    "organization_memberships": {
        "description": "A user's membership in a Calendly organization, with their role.",
        "docs_url": "https://developer.calendly.com/api-docs/aff7c447b6a05-list-organization-memberships",
        "columns": _columns(
            role="The member's role in the organization (owner, admin, or user).",
            user="The user account associated with this membership.",
            organization="URI of the organization the user is a member of.",
        ),
    },
    "routing_forms": {
        "description": "A Calendly routing form that qualifies and routes invitees to the right booking.",
        "docs_url": "https://developer.calendly.com/api-docs/c4d4f3a8aa8e4-list-routing-forms",
        "columns": _columns(
            name="Name of the routing form.",
            status="Status of the routing form: published or draft.",
            organization="URI of the organization the routing form belongs to.",
            questions="The questions configured on the routing form.",
        ),
    },
}
