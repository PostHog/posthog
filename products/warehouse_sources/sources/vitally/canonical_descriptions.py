"""Canonical, documentation-sourced descriptions for Vitally endpoints and columns.

Sourced from the official Vitally REST API reference (https://docs.vitally.io/). Keyed by the
static endpoint names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Vitally table. The per-team `Custom_Object_<name>` schemas are user-defined and discovered at
sync time, so they intentionally have no canonical entry and fall back to LLM enrichment.
Columns absent here also fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

# Fields shared by most Vitally objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object in Vitally.",
    "externalId": "Identifier for the object in your own system, used to match Vitally records.",
    "createdAt": "Time at which the object was created in Vitally.",
    "updatedAt": "Time at which the object was last updated in Vitally.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Organizations": {
        "description": "A customer organization (company) tracked in Vitally.",
        "docs_url": "https://docs.vitally.io/pushing-data-to-vitally/rest-api#organizations",
        "columns": _columns(
            name="The organization's name.",
            traits="Custom traits/attributes set on the organization.",
            accountOwnerId="ID of the Vitally user who owns this organization's account.",
            mrr="Monthly recurring revenue attributed to the organization.",
            churnedAt="Time at which the organization churned, if applicable.",
            healthScore="Current health score for the organization.",
        ),
    },
    "Accounts": {
        "description": "A customer account in Vitally, the primary unit customer success is managed against.",
        "docs_url": "https://docs.vitally.io/pushing-data-to-vitally/rest-api#accounts",
        "columns": _columns(
            name="The account's name.",
            traits="Custom traits/attributes set on the account.",
            accountOwnerId="ID of the Vitally user who owns this account.",
            organizationId="ID of the organization this account belongs to.",
            mrr="Monthly recurring revenue attributed to the account.",
            churnedAt="Time at which the account churned, if applicable.",
            healthScore="Current health score for the account.",
            nextRenewalDate="Date of the account's next contract renewal.",
        ),
    },
    "Users": {
        "description": "An end user (a person at a customer account) tracked in Vitally.",
        "docs_url": "https://docs.vitally.io/pushing-data-to-vitally/rest-api#users",
        "columns": _columns(
            name="The user's full name.",
            email="The user's email address.",
            traits="Custom traits/attributes set on the user.",
            avatar="URL of the user's avatar image.",
            lastSeenTimestamp="Time the user was last seen active.",
        ),
    },
    "Conversations": {
        "description": "A support or success conversation logged against a Vitally account or user.",
        "docs_url": "https://docs.vitally.io/pushing-data-to-vitally/rest-api#conversations",
        "columns": _columns(
            subject="The conversation's subject line.",
            accountId="ID of the account the conversation relates to.",
            externalUrl="Link to the conversation in the source system.",
            messages="The messages that make up the conversation.",
        ),
    },
    "Notes": {
        "description": "A note recorded against a Vitally account, user, or other object.",
        "docs_url": "https://docs.vitally.io/pushing-data-to-vitally/rest-api#notes",
        "columns": _columns(
            note="The note's body text.",
            accountId="ID of the account the note is attached to.",
            authorId="ID of the Vitally user who wrote the note.",
            category="Category assigned to the note.",
        ),
    },
    "Projects": {
        "description": "A project (e.g. onboarding or a success plan) tracked against a Vitally account.",
        "docs_url": "https://docs.vitally.io/pushing-data-to-vitally/rest-api#projects",
        "columns": _columns(
            name="The project's name.",
            accountId="ID of the account the project belongs to.",
            status="Current status of the project.",
            ownerId="ID of the Vitally user who owns the project.",
            completedAt="Time at which the project was completed, if applicable.",
        ),
    },
    "Tasks": {
        "description": "A task assigned to a team member in Vitally, often part of a project or playbook.",
        "docs_url": "https://docs.vitally.io/pushing-data-to-vitally/rest-api#tasks",
        "columns": _columns(
            name="The task's name.",
            accountId="ID of the account the task relates to.",
            assignedToId="ID of the Vitally user the task is assigned to.",
            status="Current status of the task.",
            dueDate="Date by which the task is due.",
            completedAt="Time at which the task was completed, if applicable.",
        ),
    },
    "NPS_Responses": {
        "description": "An NPS (Net Promoter Score) survey response collected in Vitally.",
        "docs_url": "https://docs.vitally.io/pushing-data-to-vitally/rest-api#nps-responses",
        "columns": _columns(
            score="The NPS score the respondent gave (0-10).",
            feedback="Free-text feedback provided with the score.",
            userId="ID of the user who submitted the response.",
            accountId="ID of the account the respondent belongs to.",
            npsType="Classification of the score: detractor, passive, or promoter.",
        ),
    },
    "Custom_Objects": {
        "description": "A definition of a custom object type configured in Vitally.",
        "docs_url": "https://docs.vitally.io/pushing-data-to-vitally/rest-api#custom-objects",
        "columns": _columns(
            name="Machine name of the custom object type.",
            label="Human-readable label for the custom object type.",
        ),
    },
    "Messages": {
        "description": "An individual message within a Vitally conversation.",
        "docs_url": "https://docs.vitally.io/pushing-data-to-vitally/rest-api#conversations",
        "columns": _columns(
            conversationId="ID of the conversation this message belongs to.",
            body="The message body text.",
            authorId="ID of the author who sent the message.",
            conversation_updated_at="Time at which the parent conversation was last updated.",
        ),
    },
    "Admins": {
        "description": "A Vitally admin (team member), such as the account owner or CSM referenced on other objects.",
        "docs_url": "https://docs.vitally.io/en/articles/9880663-rest-api-admins",
        "columns": {
            "id": "Vitally's unique ID for the admin.",
            "name": "The full name of the admin.",
            "email": "The email of the admin.",
            "licenseStatus": "The license status of the admin: 'active', 'deactivated' or 'auto-created'.",
            "role": "The team member role assigned to the admin, for example 'leader'.",
        },
    },
    "Meetings": {
        "description": "A customer meeting recorded in Vitally, with its participants and linked accounts.",
        "docs_url": "https://docs.vitally.io/en/articles/14501660-rest-api-meetings",
        "columns": _columns(
            title="The title of the meeting.",
            description="The description or body of the meeting.",
            location="The location of the meeting.",
            startDate="Date-only start value of the meeting, when a time is not applicable.",
            startDateTime="Time at which the meeting starts.",
            startTimeZone="Time zone of the meeting start time.",
            endDate="Date-only end value of the meeting, when a time is not applicable.",
            endDateTime="Time at which the meeting ends.",
            endTimeZone="Time zone of the meeting end time.",
            externalStatus="Status of the meeting as reported by the external source, for example 'cancelled'.",
            recordingUrl="URL of the meeting recording.",
            summary="A summary of the meeting.",
            keyPoints="Key points from the meeting.",
            riskAssessment="A risk assessment associated with the meeting.",
            source="Name of the integration that created the meeting, for example 'gong'.",
            participants="Participants of the meeting: Vitally admins, customer users and external attendees.",
            accounts="Vitally accounts associated with the meeting, resolved from its participants.",
            organizations="Vitally organizations associated with the meeting, resolved from its participants.",
            notes="Notes linked to the meeting.",
            tasks="Tasks linked to the meeting.",
            traits="Custom traits set on the meeting.",
            archivedAt="Time at which the meeting was archived.",
        ),
    },
    "Project_Templates": {
        "description": "A template that Vitally uses to create projects.",
        "docs_url": "https://docs.vitally.io/en/articles/9880869-rest-api-project-templates",
        "columns": _columns(
            name="The title of the project template.",
            projectName="The name of the projects that the template creates.",
            description="The description of the project template.",
            projectCategoryId="ID of the project category of the template.",
            traits="Custom project traits set on the template.",
        ),
    },
    "Project_Categories": {
        "description": "A category that groups Vitally project templates.",
        "docs_url": "https://docs.vitally.io/en/articles/9880869-rest-api-project-templates",
        "columns": _columns(name="The title of the project category."),
    },
}
