"""Canonical, documentation-sourced descriptions for Linear endpoints and columns.

Sourced from the official Linear GraphQL API reference (https://developers.linear.app/docs).
Keyed by the endpoint names in `settings.py` `LINEAR_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Linear table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Linear objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "createdAt": "Time at which the object was first created.",
    "updatedAt": "Time at which the object was last updated.",
    "archivedAt": "Time at which the object was archived, if it has been archived.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "issues": {
        "description": "A unit of work tracked in Linear — a task, bug, or feature request.",
        "docs_url": "https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
        "columns": _columns(
            title="The issue's title.",
            description="The issue's description in markdown.",
            priority="Priority of the issue (0 = no priority, 1 = urgent, 2 = high, 3 = normal, 4 = low).",
            identifier="Human-readable issue identifier (e.g. ENG-123).",
            number="Issue's unique number within its team.",
            state="Workflow state (status) the issue is currently in.",
            assignee="The user assigned to work on the issue.",
            creator="The user who created the issue.",
            team="The team the issue belongs to.",
            project="The project the issue is part of, if any.",
            estimate="Estimate of the issue's complexity or effort in points.",
            dueDate="Date by which the issue should be completed.",
            startedAt="Time at which the issue was moved into a started state.",
            completedAt="Time at which the issue was completed.",
            canceledAt="Time at which the issue was canceled.",
        ),
    },
    "projects": {
        "description": "A collection of issues working toward a common goal, with a timeline and progress.",
        "docs_url": "https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
        "columns": _columns(
            name="The project's name.",
            description="Short summary of the project.",
            state="The project's current status (e.g. planned, started, completed, canceled).",
            progress="Completion progress of the project, from 0 to 1.",
            lead="The user leading the project.",
            creator="The user who created the project.",
            startDate="Planned start date of the project.",
            targetDate="Planned target (completion) date of the project.",
            startedAt="Time at which the project was started.",
            completedAt="Time at which the project was completed.",
            canceledAt="Time at which the project was canceled.",
        ),
    },
    "teams": {
        "description": "A team in the Linear workspace that owns issues, projects, and a workflow.",
        "docs_url": "https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
        "columns": _columns(
            name="The team's name.",
            key="The team's short key, used as a prefix for issue identifiers (e.g. ENG).",
            description="Description of the team.",
            private="Whether the team is private to its members.",
        ),
    },
    "users": {
        "description": "A member of the Linear workspace.",
        "docs_url": "https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
        "columns": _columns(
            name="The user's full name.",
            displayName="The user's display name, unique within the workspace.",
            email="The user's email address.",
            active="Whether the user account is active.",
            admin="Whether the user is an admin of the workspace.",
            guest="Whether the user is a guest with restricted access.",
            lastSeen="Time the user was last active in Linear.",
        ),
    },
    "comments": {
        "description": "A comment left by a user on an issue or project in Linear.",
        "docs_url": "https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
        "columns": _columns(
            body="The comment's content in markdown.",
            user="The user who wrote the comment.",
            issue="The issue the comment was left on.",
            parent="The parent comment, if this comment is a threaded reply.",
            editedAt="Time at which the comment was last edited.",
        ),
    },
    "labels": {
        "description": "A label that can be applied to issues to categorize them.",
        "docs_url": "https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
        "columns": _columns(
            name="The label's name.",
            description="Description of the label.",
            color="The label's color, as a hex value.",
            team="The team the label belongs to, if it is team-scoped.",
            parent="The parent label, if this label is part of a group.",
        ),
    },
    "cycles": {
        "description": "A time-boxed sprint of work for a team, with a set of issues and a date range.",
        "docs_url": "https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
        "columns": _columns(
            name="The cycle's name.",
            number="The cycle's sequential number within its team.",
            description="Description of the cycle.",
            team="The team the cycle belongs to.",
            startsAt="Start time of the cycle.",
            endsAt="End time of the cycle.",
            completedAt="Time at which the cycle was completed.",
            progress="Completion progress of the cycle, from 0 to 1.",
        ),
    },
    "resources": {
        "description": "An attachment linking an issue to an external resource (a URL, document, or integration).",
        "docs_url": "https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
        "columns": _columns(
            title="The attachment's title.",
            subtitle="The attachment's subtitle.",
            url="The external URL the attachment points to.",
            issue="The issue the attachment is associated with.",
            creator="The user who created the attachment.",
            source="Information about the integration or service that created the attachment.",
        ),
    },
    "workflow_states": {
        "description": "An issue workflow state (status) belonging to a team, such as Todo, In Progress, or Done.",
        "docs_url": "https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
        "columns": _columns(
            name="The state's name.",
            type="Category of the state: triage, backlog, unstarted, started, completed, or canceled.",
            color="The state's UI color, as a hex value.",
            description="Description of the state.",
            position="The state's position in the team's workflow.",
            team="The team this workflow state belongs to.",
            inheritedFrom="The workspace-level state this team state was inherited from, if any.",
        ),
    },
    "project_milestones": {
        "description": "A milestone marking a checkpoint within a project, grouping issues due by a target date.",
        "docs_url": "https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
        "columns": _columns(
            name="The milestone's name.",
            description="Description of the milestone.",
            status="Current status of the milestone (unstarted, next, overdue, or done).",
            progress="Completion progress of the milestone, from 0 to 1.",
            sortOrder="Position of the milestone within its project.",
            targetDate="Date by which the milestone should be completed.",
            project="The project the milestone belongs to.",
        ),
    },
    "initiatives": {
        "description": "A strategic goal that groups related projects together across the workspace.",
        "docs_url": "https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
        "columns": _columns(
            name="The initiative's name.",
            description="Short summary of the initiative.",
            content="The initiative's full description in markdown.",
            slugId="URL-friendly identifier for the initiative.",
            status="Current status of the initiative (Planned, Active, or Completed).",
            health="Health reported in the initiative's latest update (onTrack, atRisk, or offTrack).",
            priority="Priority of the initiative (0 = no priority, 1 = urgent, 2 = high, 3 = normal, 4 = low).",
            sortOrder="Position of the initiative in the workspace list.",
            targetDate="Date by which the initiative should be completed.",
            targetDateResolution="Granularity of the target date (day, month, quarter, or year).",
            startedAt="Time at which the initiative was moved into a started status.",
            completedAt="Time at which the initiative was completed.",
            healthUpdatedAt="Time at which the initiative's health was last updated.",
            trashed="Whether the initiative has been moved to the trash.",
            creator="The user who created the initiative.",
            owner="The user who owns the initiative.",
            parentInitiative="The parent initiative, if this initiative is nested.",
            url="Link to the initiative in the Linear app.",
        ),
    },
    "team_memberships": {
        "description": "The membership of a user in a team, including whether they own it.",
        "docs_url": "https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
        "columns": _columns(
            owner="Whether the user is an owner of the team.",
            sortOrder="Position of the team in the user's team list.",
            team="The team the membership belongs to.",
            user="The user who is a member of the team.",
        ),
    },
    "issue_relations": {
        "description": "A directed relationship between two issues, such as blocks, blocked by, related, or duplicate.",
        "docs_url": "https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
        "columns": _columns(
            type="The type of relation: blocks, duplicate, related, or similar.",
            issue="The issue the relation starts from.",
            relatedIssue="The issue on the other side of the relation.",
        ),
    },
    "project_updates": {
        "description": "A written status update posted on a project, recording its health at a point in time.",
        "docs_url": "https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
        "columns": _columns(
            body="The update's content in markdown.",
            health="Health reported in the update (onTrack, atRisk, or offTrack).",
            url="Link to the update in the Linear app.",
            slugId="URL-friendly identifier for the update.",
            commentCount="Number of comments left on the update.",
            isStale="Whether the update is stale because a newer one has been posted.",
            isDiffHidden="Whether the diff between this update and the previous one is hidden.",
            diffMarkdown="Markdown diff between this update and the previous one.",
            editedAt="Time at which the update was last edited.",
            project="The project the update was posted on.",
            user="The user who posted the update.",
        ),
    },
    "documents": {
        "description": "A document written in Linear, optionally attached to a project, initiative, or issue.",
        "docs_url": "https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
        "columns": _columns(
            title="The document's title.",
            content="The document's content in markdown.",
            icon="Icon shown for the document.",
            color="The document's color, as a hex value.",
            slugId="URL-friendly identifier for the document.",
            url="Link to the document in the Linear app.",
            trashed="Whether the document has been moved to the trash.",
            hiddenAt="Time at which the document was hidden.",
            creator="The user who created the document.",
            updatedBy="The user who last updated the document.",
            project="The project the document belongs to, if any.",
            initiative="The initiative the document belongs to, if any.",
            issue="The issue the document belongs to, if any.",
        ),
    },
}
