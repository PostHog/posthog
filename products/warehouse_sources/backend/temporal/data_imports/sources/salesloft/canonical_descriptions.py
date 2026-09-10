"""Canonical, documentation-sourced descriptions for Salesloft endpoints and columns.

Sourced from the official Salesloft API reference (https://developers.salesloft.com/docs/api).
Keyed by the resource names in `settings.py` `SALESLOFT_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Salesloft table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Salesloft resources; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "created_at": "Time at which the object was created.",
    "updated_at": "Time at which the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "accounts": {
        "description": "A company or organization that people in Salesloft belong to.",
        "docs_url": "https://developers.salesloft.com/docs/api/accounts-index",
        "columns": _columns(
            name="Name of the account.",
            domain="Website domain of the account.",
            phone="Primary phone number of the account.",
            industry="Industry the account operates in.",
            company_type="Type of company.",
            owner="The user who owns the account.",
            account_tier="The tier assigned to the account.",
            account_stage="The stage the account is in.",
            archived_at="Time at which the account was archived, if archived.",
        ),
    },
    "account_stages": {
        "description": "A stage that an account can be assigned to, representing its position in a workflow.",
        "docs_url": "https://developers.salesloft.com/docs/api/account-stages-index",
        "columns": _columns(
            name="Name of the account stage.",
            order="Sort order of the stage.",
        ),
    },
    "account_tiers": {
        "description": "A tier used to classify the importance of accounts.",
        "docs_url": "https://developers.salesloft.com/docs/api/account-tiers-index",
        "columns": _columns(
            name="Name of the account tier.",
            order="Sort order of the tier.",
            active="Whether the tier is active.",
        ),
    },
    "actions": {
        "description": "A pending step in a cadence that a user needs to complete for a person.",
        "docs_url": "https://developers.salesloft.com/docs/api/actions-index",
        "columns": _columns(
            type="Type of action (e.g. email, phone, integration).",
            status="Status of the action (e.g. pending_action, completed).",
            due="Whether the action is currently due.",
            due_on="Date the action is due.",
            user="The user the action is assigned to.",
            person="The person the action relates to.",
            cadence="The cadence the action belongs to.",
            step="The cadence step the action corresponds to.",
        ),
    },
    "cadences": {
        "description": "A sequence of automated and manual outreach steps run against people.",
        "docs_url": "https://developers.salesloft.com/docs/api/cadences-index",
        "columns": _columns(
            name="Name of the cadence.",
            cadence_function="The function of the cadence (e.g. outbound, inbound).",
            team_cadence="Whether the cadence is shared across the team.",
            shared="Whether the cadence is shared.",
            archived="Whether the cadence is archived.",
            owner="The user who owns the cadence.",
            creator="The user who created the cadence.",
        ),
    },
    "cadence_memberships": {
        "description": "The relationship between a person and a cadence they are enrolled in.",
        "docs_url": "https://developers.salesloft.com/docs/api/cadence-memberships-index",
        "columns": _columns(
            person="The person enrolled in the cadence.",
            cadence="The cadence the person is enrolled in.",
            user="The user who added the person to the cadence.",
            current_state="Current state of the membership in the cadence.",
            added_at="Time at which the person was added to the cadence.",
            currently_on_cadence="Whether the person is currently active on the cadence.",
        ),
    },
    "call_data_records": {
        "description": "A record of a call's metadata, including duration and recording details.",
        "docs_url": "https://developers.salesloft.com/docs/api/call-data-records-index",
        "columns": _columns(
            direction="Direction of the call (inbound or outbound).",
            duration="Duration of the call in seconds.",
            recording="Information about the call recording.",
            to="The phone number that was called.",
            from_="The phone number the call came from.",
            user="The user who made or received the call.",
            person="The person the call was with.",
            called_person="The person who was called.",
        ),
    },
    "calls": {
        "description": "A logged phone call activity made through Salesloft.",
        "docs_url": "https://developers.salesloft.com/docs/api/activities-calls-index",
        "columns": _columns(
            user="The user who made the call.",
            person="The person who was called.",
            sentiment="The recorded sentiment of the call.",
            disposition="The disposition (outcome) of the call.",
            duration="Duration of the call in seconds.",
            crm_activity="The CRM activity logged for the call.",
            called_person="The person who was called.",
        ),
    },
    "call_dispositions": {
        "description": "A possible outcome that can be recorded for a call.",
        "docs_url": "https://developers.salesloft.com/docs/api/call-dispositions-index",
        "columns": {"name": "Name of the call disposition."},
    },
    "call_sentiments": {
        "description": "A possible sentiment that can be recorded for a call.",
        "docs_url": "https://developers.salesloft.com/docs/api/call-sentiments-index",
        "columns": {"name": "Name of the call sentiment."},
    },
    "crm_activities": {
        "description": "An activity synced to the connected CRM, such as a logged call or email.",
        "docs_url": "https://developers.salesloft.com/docs/api/crm-activities-index",
        "columns": _columns(
            subject="Subject of the CRM activity.",
            description="Description of the CRM activity.",
            activity_type="Type of the CRM activity.",
            user="The user associated with the activity.",
            person="The person the activity relates to.",
            crm_id="Identifier of the activity in the connected CRM.",
        ),
    },
    "crm_users": {
        "description": "A user record synced from the connected CRM.",
        "docs_url": "https://developers.salesloft.com/docs/api/crm-users-index",
        "columns": _columns(
            crm_id="Identifier of the user in the connected CRM.",
            user="The matching Salesloft user, if linked.",
        ),
    },
    "custom_fields": {
        "description": "A custom field definition that can be applied to people, companies, or opportunities.",
        "docs_url": "https://developers.salesloft.com/docs/api/custom-fields-index",
        "columns": _columns(
            name="Name of the custom field.",
            field_type="The type of object the custom field applies to.",
        ),
    },
    "emails": {
        "description": "A logged email activity sent through Salesloft.",
        "docs_url": "https://developers.salesloft.com/docs/api/activities-emails-index",
        "columns": _columns(
            user="The user who sent the email.",
            recipient="The person the email was sent to.",
            recipient_email_address="Email address the email was sent to.",
            mailing="The mailing the email belongs to.",
            subject="Subject line of the email.",
            status="Delivery status of the email.",
            bounced="Whether the email bounced.",
            send_after="Time after which the email is scheduled to send.",
            view_tracking="Whether open tracking is enabled for the email.",
            click_tracking="Whether click tracking is enabled for the email.",
            counts="Counts of views, clicks, and replies for the email.",
        ),
    },
    "email_templates": {
        "description": "A reusable email template used in cadences and one-off sends.",
        "docs_url": "https://developers.salesloft.com/docs/api/email-templates-index",
        "columns": _columns(
            title="Title of the email template.",
            subject="Default subject line of the template.",
            body_preview="Preview text of the template body.",
            archived_at="Time at which the template was archived, if archived.",
            shared="Whether the template is shared across the team.",
            open_tracking_enabled="Whether open tracking is enabled by default.",
            click_tracking_enabled="Whether click tracking is enabled by default.",
            counts="Aggregate sent, view, click, and reply counts for the template.",
        ),
    },
    "email_template_attachments": {
        "description": "A file attached to an email template.",
        "docs_url": "https://developers.salesloft.com/docs/api/email-template-attachments-index",
        "columns": {
            "id": "Unique identifier for the attachment.",
            "attachment_id": "Identifier of the underlying attachment.",
            "name": "File name of the attachment.",
            "download_url": "URL to download the attachment.",
            "email_template": "The email template the attachment belongs to.",
        },
    },
    "groups": {
        "description": "A group of users within the Salesloft team.",
        "docs_url": "https://developers.salesloft.com/docs/api/groups-index",
        "columns": {
            "id": "Unique identifier for the group.",
            "name": "Name of the group.",
            "parent_id": "ID of the parent group, if any.",
        },
    },
    "imports": {
        "description": "A batch import of people into Salesloft.",
        "docs_url": "https://developers.salesloft.com/docs/api/imports-index",
        "columns": _columns(
            name="Name of the import.",
            current_people_count="Current number of people associated with the import.",
            imported_people_count="Number of people imported in the batch.",
        ),
    },
    "meetings": {
        "description": "A scheduled meeting booked through Salesloft.",
        "docs_url": "https://developers.salesloft.com/docs/api/meetings-index",
        "columns": _columns(
            title="Title of the meeting.",
            start_time="Start time of the meeting.",
            end_time="End time of the meeting.",
            status="Status of the meeting (e.g. booked, canceled).",
            meeting_type="Type of the meeting.",
            person="The person the meeting is with.",
            owner="The user who owns the meeting.",
            booked_by_user="The user who booked the meeting.",
            location="Location of the meeting.",
            canceled_at="Time at which the meeting was canceled, if canceled.",
        ),
    },
    "notes": {
        "description": "A note recorded against a person or account.",
        "docs_url": "https://developers.salesloft.com/docs/api/notes-index",
        "columns": _columns(
            content="Text content of the note.",
            user="The user who created the note.",
            associated_type="Type of object the note is associated with.",
            associated_id="ID of the object the note is associated with.",
        ),
    },
    "people": {
        "description": "An individual contact tracked in Salesloft.",
        "docs_url": "https://developers.salesloft.com/docs/api/people-index",
        "columns": _columns(
            first_name="Person's first name.",
            last_name="Person's last name.",
            display_name="Person's display name.",
            email_address="Person's primary email address.",
            phone="Person's phone number.",
            title="Person's job title.",
            account="The account the person belongs to.",
            owner="The user who owns the person.",
            person_stage="The stage the person is in.",
            person_company_name="Name of the person's company.",
            do_not_contact="Whether the person is marked do-not-contact.",
            contact_restrictions="Any contact restrictions on the person.",
        ),
    },
    "person_stages": {
        "description": "A stage that a person can be assigned to, representing their lifecycle position.",
        "docs_url": "https://developers.salesloft.com/docs/api/person-stages-index",
        "columns": _columns(
            name="Name of the person stage.",
            order="Sort order of the stage.",
        ),
    },
    "phone_number_assignments": {
        "description": "The assignment of a phone number to a user for calling.",
        "docs_url": "https://developers.salesloft.com/docs/api/phone-number-assignments-index",
        "columns": {
            "id": "Unique identifier for the assignment.",
            "number": "The assigned phone number.",
            "user": "The user the phone number is assigned to.",
        },
    },
    "steps": {
        "description": "A single step within a cadence (an email, call, or other action).",
        "docs_url": "https://developers.salesloft.com/docs/api/steps-index",
        "columns": _columns(
            name="Name of the step.",
            type="Type of the step (e.g. email, phone, other).",
            step_number="Position of the step within its cadence day.",
            day="The cadence day the step falls on.",
            cadence="The cadence the step belongs to.",
            disabled="Whether the step is disabled.",
        ),
    },
    "successes": {
        "description": "A recorded success outcome for a person, such as a positive reply or meeting.",
        "docs_url": "https://developers.salesloft.com/docs/api/successes-index",
        "columns": _columns(
            person="The person the success is recorded for.",
            user="The user credited with the success.",
            succeeded_at="Time at which the success occurred.",
        ),
    },
    "team_templates": {
        "description": "An email template shared and managed at the team level.",
        "docs_url": "https://developers.salesloft.com/docs/api/team-templates-index",
        "columns": _columns(
            title="Title of the team template.",
            subject="Default subject line of the template.",
            body_preview="Preview text of the template body.",
            archived_at="Time at which the template was archived, if archived.",
            counts="Aggregate sent, view, click, and reply counts for the template.",
        ),
    },
    "team_template_attachments": {
        "description": "A file attached to a team template.",
        "docs_url": "https://developers.salesloft.com/docs/api/team-template-attachments-index",
        "columns": {
            "id": "Unique identifier for the attachment.",
            "attachment_id": "Identifier of the underlying attachment.",
            "name": "File name of the attachment.",
            "download_url": "URL to download the attachment.",
            "team_template": "The team template the attachment belongs to.",
        },
    },
    "users": {
        "description": "A Salesloft user account.",
        "docs_url": "https://developers.salesloft.com/docs/api/users-index",
        "columns": _columns(
            name="The user's full name.",
            first_name="The user's first name.",
            last_name="The user's last name.",
            email="The user's email address.",
            active="Whether the user account is active.",
            guid="Globally unique identifier for the user.",
            group="The group the user belongs to.",
            role="The user's role.",
            team_admin="Whether the user is a team admin.",
            phone_number_assignment="The phone number assigned to the user.",
        ),
    },
}
