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
    "invitees": {
        "description": "A person who booked a scheduled event, with their answers, tracking and cancellation.",
        "docs_url": "https://developer.calendly.com/api-docs/e55b39ce6b6f2-list-event-invitees",
        "columns": _columns(
            email="The invitee's email address.",
            name="The invitee's name (in human-readable format).",
            first_name="First name of the invitee, when the event type collects first and last name separately.",
            last_name="Last name of the invitee, when the event type collects first and last name separately.",
            status="Whether the invitee is active or canceled.",
            event="URI of the scheduled event the invitee booked.",
            questions_and_answers="The invitee's responses to the questions on the booking confirmation form.",
            timezone="Time zone used when displaying times to the invitee.",
            tracking="UTM and Salesforce tracking parameters captured from the booking link.",
            text_reminder_number="Phone number used for text (SMS) reminders.",
            rescheduled="Whether this invitee rescheduled; the replacement is linked in new_invitee.",
            old_invitee="URI of the invitee record that was rescheduled into this one.",
            new_invitee="URI of the invitee record created when this one was rescheduled.",
            cancel_url="Link the invitee uses to cancel the event.",
            reschedule_url="Link the invitee uses to reschedule the event.",
            routing_form_submission="URI of the routing form submission that sent the invitee to this booking page.",
            cancellation="Cancellation details, present when the booking has been canceled.",
            payment="Payment collected for the booking.",
            no_show="No-show record for the invitee, present when they were marked as a no-show.",
            reconfirmation="Reconfirmation request details, when the event type requires reconfirmation.",
            scheduling_method="How the event was scheduled.",
            invitee_scheduled_by="URI of the user who scheduled the event on the invitee's behalf.",
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
    "routing_form_submissions": {
        "description": "A completed routing form submission and where the respondent was routed.",
        "docs_url": "https://developer.calendly.com/api-docs/6f5b9ed0f8b76-list-routing-form-submissions",
        "columns": _columns(
            routing_form="URI of the routing form that was submitted.",
            questions_and_answers="The respondent's answers to the routing form questions.",
            tracking="UTM and Salesforce tracking parameters captured with the submission.",
            result="Where the submission routed the respondent: an event type, an external URL, or a custom message.",
            submitter="URI of the invitee resource, when the submission ended in a booked meeting.",
            submitter_type="Type of respondent that submitted the form and scheduled a meeting.",
        ),
    },
    "event_type_memberships": {
        "description": "A host assigned to an event type, joining event types to the users who run them.",
        "docs_url": "https://developer.calendly.com/api-docs/d07d3d2ba5b76-list-event-type-hosts",
        "columns": _columns(
            event_type="The event type the host is assigned to.",
            member="The user hosting the event type.",
        ),
    },
    "contacts": {
        "description": "A person in the Calendly contacts directory, which invitee emails resolve against.",
        "docs_url": "https://developer.calendly.com/api-docs/b3A6NjM0Mzg0MTA-list-contacts",
        "columns": _columns(
            emails="The contact's email addresses (up to 10).",
            name="The contact's name (in human-readable format).",
            phone_numbers="The contact's phone numbers (up to 10).",
            timezone="Time zone used when presenting times to the contact.",
            job_title="The contact's job title.",
            company="The contact's company name.",
            country="Two-letter country code for the contact (ISO 3166-1 alpha-2).",
            state="The contact's state, province, or region.",
            city="The contact's city.",
            linkedin="URL of the contact's LinkedIn profile.",
            custom_fields="Values the contact has for the account's custom contact fields.",
            first_email_date="Time of the earliest email exchanged with the contact.",
            last_email_date="Time of the most recent email exchanged with the contact.",
            next_meeting_date="Time of the next upcoming meeting scheduled with the contact.",
            last_meeting_date="Time of the most recent meeting held with the contact.",
            last_interaction_date="Time of the most recent email or meeting with the contact.",
        ),
    },
}
