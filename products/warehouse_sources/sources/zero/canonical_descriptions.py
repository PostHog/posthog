"""Canonical, documentation-sourced descriptions for Zero endpoints and columns.

Sourced from the official Zero API reference (https://docs.zero.inc/features/api). Keyed by the
resource names in `settings.py` `ENDPOINT_CONFIGS`, which match the `ExternalDataSchema.name` of a
synced Zero table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most workspace-scoped Zero objects; merged into each entry so they aren't repeated.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the record.",
    "workspaceId": "Identifier of the workspace the record belongs to.",
    "createdAt": "Time at which the record was created.",
    "updatedAt": "Time at which the record was last updated.",
    "archived": "Whether the record has been archived.",
    "createdById": "Identifier of the user who created the record.",
    "externalId": "Identifier of the record in the system it was imported from, if any.",
    "source": "Where the record originated from (e.g. manual entry, email capture, import).",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Workspaces": {
        "description": "The Zero workspace the connected API key belongs to.",
        "docs_url": "https://docs.zero.inc/features/api/workspaces",
        "columns": {
            "id": "Unique identifier for the workspace.",
            "name": "Name of the workspace.",
            "key": "URL-safe identifier for the workspace.",
            "domain": "Primary email domain associated with the workspace.",
            "domains": "All email domains associated with the workspace.",
            "trialEndsAt": "Time at which the workspace's trial period ends, if applicable.",
            "archived": "Whether the workspace has been archived.",
            "createdAt": "Time at which the workspace was created.",
            "updatedAt": "Time at which the workspace was last updated.",
        },
    },
    "Companies": {
        "description": "A company (account) tracked in the CRM, auto-captured from email and calendar activity.",
        "docs_url": "https://docs.zero.inc/features/api/companies",
        "columns": _columns(
            name="Name of the company.",
            domain="Primary domain of the company.",
            description="Free-text description of the company.",
            linkedin="LinkedIn URL for the company.",
            logo="URL of the company's logo.",
            listIds="Identifiers of the lists the company belongs to.",
            ownerIds="Identifiers of the users who own the company.",
            location="Location of the company (city, state, country, coordinates).",
            parentCompanyId="Identifier of the company's parent company, if any.",
            custom="Custom property values defined by the workspace, keyed by property id.",
        ),
    },
    "Contacts": {
        "description": "A person tracked in the CRM, auto-captured from email, calendar, and call activity.",
        "docs_url": "https://docs.zero.inc/features/api/contacts",
        "columns": _columns(
            companyId="Identifier of the company the contact belongs to.",
            name="Full name of the contact.",
            email="Primary email address of the contact.",
            title="Job title of the contact.",
            phone="Phone number of the contact.",
            linkedin="LinkedIn username of the contact.",
            location="Location of the contact.",
            type="Type of contact record.",
            listIds="Identifiers of the lists the contact belongs to.",
            ownerIds="Identifiers of the users who own the contact.",
            custom="Custom property values defined by the workspace, keyed by property id.",
            unsubscribedFromAllMessaging="Whether the contact has unsubscribed from all outbound messaging.",
            unsubscribedFromAllMessagingAt="Time at which the contact unsubscribed from all outbound messaging.",
        ),
    },
    "Deals": {
        "description": "An opportunity moving through a sales pipeline.",
        "docs_url": "https://docs.zero.inc/features/api/deals",
        "columns": _columns(
            pipelineId="Identifier of the pipeline the deal belongs to.",
            companyId="Identifier of the company the deal is associated with.",
            contactIds="Identifiers of the contacts associated with the deal.",
            name="Name of the deal.",
            stage="Identifier of the pipeline stage the deal is currently in.",
            value="Monetary value of the deal.",
            confidence="Confidence (0.0-1.0) that the deal will close.",
            closeDate="Expected or actual close date of the deal.",
            startDate="Date the deal was opened.",
            endDate="Date the deal was closed, if closed.",
            listIds="Identifiers of the lists the deal belongs to.",
            ownerIds="Identifiers of the users who own the deal.",
            custom="Custom property values defined by the workspace, keyed by property id.",
        ),
    },
    "Pipelines": {
        "description": "A sales pipeline used to track deals through a sequence of stages.",
        "docs_url": "https://docs.zero.inc/features/api/pipelines",
        "columns": _columns(
            name="Name of the pipeline.",
            description="Free-text description of the pipeline.",
            icon="Icon shown for the pipeline in the UI.",
            color="Hex color shown for the pipeline in the UI.",
            confidenceEnabled="Whether deals in this pipeline track a win confidence score.",
            defaultStage="Identifier of the stage new deals are created in.",
            order="Sort order of the pipeline relative to other pipelines.",
        ),
    },
    "PipelineStages": {
        "description": "A stage within a sales pipeline (e.g. lead, in-progress, won, lost).",
        "docs_url": "https://docs.zero.inc/features/api/pipeline-stages",
        "columns": _columns(
            pipelineId="Identifier of the pipeline this stage belongs to.",
            name="Name of the stage.",
            description="Free-text description of the stage.",
            type="Category of the stage: lead, in-progress, won, or lost.",
            confidence="Default win confidence (0.0-1.0) for deals in this stage.",
            icon="Icon shown for the stage in the UI.",
            color="Hex color shown for the stage in the UI.",
            order="Sort order of the stage within its pipeline.",
        ),
    },
    "Notes": {
        "description": "A note attached to a company, contact, or deal.",
        "docs_url": "https://docs.zero.inc/features/api/notes",
        "columns": _columns(
            name="Title of the note.",
            emoji="Emoji icon shown for the note.",
            content="Body of the note, in Tiptap document format.",
            companyId="Identifier of the company the note is attached to, if any.",
            contactId="Identifier of the contact the note is attached to, if any.",
            dealId="Identifier of the deal the note is attached to, if any.",
        ),
    },
    "Tasks": {
        "description": "A to-do item, optionally linked to companies, contacts, or deals.",
        "docs_url": "https://docs.zero.inc/features/api/tasks",
        "columns": _columns(
            name="Title of the task.",
            done="Whether the task has been completed.",
            priority="Priority of the task.",
            deadline="Due date of the task.",
            content="Rich-text body of the task.",
            description="Free-text description of the task.",
            companyIds="Identifiers of the companies the task is linked to.",
            contactIds="Identifiers of the contacts the task is linked to.",
            dealIds="Identifiers of the deals the task is linked to.",
            assignedToIds="Identifiers of the users the task is assigned to.",
            type="Type of task.",
            message="Message associated with the task, if any.",
        ),
    },
    "Meetings": {
        "description": "A calendar event, optionally linked to companies, contacts, or deals.",
        "docs_url": "https://docs.zero.inc/features/api/meetings",
        "columns": _columns(
            name="Title of the meeting.",
            startTime="Start time of the meeting.",
            endTime="End time of the meeting.",
            location="Location of the meeting.",
            description="Free-text description of the meeting.",
            organizer="Email and display name of the meeting organizer.",
            attendeeEmails="Email addresses of the meeting's attendees.",
            meetingLink="Video conferencing URL for the meeting.",
            summary="AI-generated summary of the meeting, in Tiptap document format.",
            userIds="Identifiers of the workspace users attending the meeting.",
            companyIds="Identifiers of the companies linked to the meeting.",
            contactIds="Identifiers of the contacts linked to the meeting.",
            dealIds="Identifiers of the deals linked to the meeting.",
            busy="Whether the meeting marks the attendees as busy.",
            external="Whether the meeting was synced from an external calendar.",
            audioUrl="URL of the meeting's audio recording, if any.",
            videoUrl="URL of the meeting's video recording, if any.",
        ),
    },
    "Memberships": {
        "description": "A user's membership in the workspace, including their role.",
        "docs_url": "https://docs.zero.inc/features/api/memberships",
        "columns": {
            "id": "Unique identifier for the membership.",
            "userId": "Identifier of the user who is a member of the workspace.",
            "workspaceId": "Identifier of the workspace the user is a member of.",
            "role": "Role the user holds in the workspace.",
            "invitedById": "Identifier of the user who sent the invite.",
            "archived": "Whether the membership has been archived (the member removed).",
            "createdAt": "Time at which the membership was created.",
            "updatedAt": "Time at which the membership was last updated.",
        },
    },
    "Users": {
        "description": "A user with access to the workspace.",
        "docs_url": "https://docs.zero.inc/features/api/users",
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "Full name of the user.",
            "email": "Email address of the user.",
            "title": "Job title of the user.",
            "avatar": "URL of the user's profile picture.",
            "linkedin": "LinkedIn username of the user.",
            "active": "Whether the user's account is active.",
            "emailConfirmed": "Whether the user has confirmed their email address.",
            "lastSeenAt": "Time at which the user was last active.",
            "createdAt": "Time at which the user account was created.",
            "updatedAt": "Time at which the user account was last updated.",
        },
    },
}
