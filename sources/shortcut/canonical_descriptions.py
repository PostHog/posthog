"""Canonical, documentation-sourced descriptions for Shortcut endpoints and columns.

Sourced from the official Shortcut REST API v3 reference (https://developer.shortcut.com/api/rest/v3).
Keyed by the endpoint names in `settings.py` `SHORTCUT_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Shortcut table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Shortcut objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "entity_type": "String describing the object's Shortcut type (e.g. 'story', 'epic').",
    "created_at": "Time at which the object was created.",
    "updated_at": "Time at which the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "members": {
        "description": "A user account that is a member of the Shortcut workspace.",
        "docs_url": "https://developer.shortcut.com/api/rest/v3#Member",
        "columns": _columns(
            profile="The member's profile, including name, email, and Mention name.",
            role="The member's role in the workspace (e.g. member, admin, owner).",
            disabled="Whether the member account is disabled.",
        ),
    },
    "groups": {
        "description": "A team (group) in Shortcut that owns stories and epics.",
        "docs_url": "https://developer.shortcut.com/api/rest/v3#Group",
        "columns": _columns(
            name="The group's name.",
            description="Description of the group.",
            mention_name="The group's @-mention handle.",
            member_ids="IDs of the members belonging to the group.",
            archived="Whether the group has been archived.",
        ),
    },
    "projects": {
        "description": "A project that organizes a collection of related stories.",
        "docs_url": "https://developer.shortcut.com/api/rest/v3#Project",
        "columns": _columns(
            name="The project's name.",
            description="Description of the project.",
            team_id="ID of the team the project belongs to.",
            color="The project's color.",
            archived="Whether the project has been archived.",
        ),
    },
    "workflows": {
        "description": "A workflow defining the set of states a story moves through.",
        "docs_url": "https://developer.shortcut.com/api/rest/v3#Workflow",
        "columns": _columns(
            name="The workflow's name.",
            description="Description of the workflow.",
            default_state_id="ID of the workflow state new stories start in.",
            states="The ordered list of states that make up the workflow.",
            team_id="ID of the team the workflow belongs to.",
        ),
    },
    "epics": {
        "description": "An epic grouping a set of stories working toward a larger goal.",
        "docs_url": "https://developer.shortcut.com/api/rest/v3#Epic",
        "columns": _columns(
            name="The epic's name.",
            description="Description of the epic.",
            state="Current workflow state of the epic.",
            epic_state_id="ID of the epic's workflow state.",
            owner_ids="IDs of the members who own the epic.",
            requested_by_id="ID of the member who requested the epic.",
            milestone_id="ID of the milestone (objective) the epic belongs to.",
            deadline="The epic's due date, if set.",
            started_at="Time at which work on the epic started.",
            completed_at="Time at which the epic was completed.",
            archived="Whether the epic has been archived.",
        ),
    },
    "iterations": {
        "description": "A time-boxed iteration (sprint) of work with a start and end date.",
        "docs_url": "https://developer.shortcut.com/api/rest/v3#Iteration",
        "columns": _columns(
            name="The iteration's name.",
            description="Description of the iteration.",
            status="Current status of the iteration (e.g. unstarted, started, done).",
            start_date="Start date of the iteration.",
            end_date="End date of the iteration.",
            group_ids="IDs of the groups associated with the iteration.",
        ),
    },
    "labels": {
        "description": "A label that can be applied to stories and epics to categorize them.",
        "docs_url": "https://developer.shortcut.com/api/rest/v3#Label",
        "columns": _columns(
            name="The label's name.",
            description="Description of the label.",
            color="The label's color.",
            archived="Whether the label has been archived.",
        ),
    },
    "categories": {
        "description": "A category used to group objectives (milestones).",
        "docs_url": "https://developer.shortcut.com/api/rest/v3#Category",
        "columns": _columns(
            name="The category's name.",
            type="The type of entity the category applies to.",
            color="The category's color.",
            archived="Whether the category has been archived.",
        ),
    },
    "objectives": {
        "description": "An objective (milestone) representing a high-level goal spanning multiple epics.",
        "docs_url": "https://developer.shortcut.com/api/rest/v3#Milestone",
        "columns": _columns(
            name="The objective's name.",
            description="Description of the objective.",
            state="Current state of the objective (e.g. to do, in progress, done).",
            categories="Categories applied to the objective.",
            started_at="Time at which work on the objective started.",
            completed_at="Time at which the objective was completed.",
            archived="Whether the objective has been archived.",
        ),
    },
    "custom_fields": {
        "description": "A custom field definition that can hold structured values on stories.",
        "docs_url": "https://developer.shortcut.com/api/rest/v3#CustomField",
        "columns": _columns(
            name="The custom field's name.",
            field_type="The type of the custom field (e.g. enum).",
            enabled="Whether the custom field is enabled.",
            values="The allowed values for the custom field.",
            canonical_name="The canonical name of the custom field, if it maps to a built-in concept.",
        ),
    },
    "files": {
        "description": "A file uploaded to Shortcut and attached to a story.",
        "docs_url": "https://developer.shortcut.com/api/rest/v3#File",
        "columns": _columns(
            name="The file's name.",
            description="Description of the file.",
            content_type="MIME content type of the file.",
            size="Size of the file in bytes.",
            uploader_id="ID of the member who uploaded the file.",
            story_ids="IDs of the stories the file is attached to.",
            url="URL where the file can be downloaded.",
        ),
    },
    "linked_files": {
        "description": "A reference to a file hosted in an external service (e.g. Google Drive, Dropbox) linked to a story.",
        "docs_url": "https://developer.shortcut.com/api/rest/v3#LinkedFile",
        "columns": _columns(
            name="The linked file's name.",
            description="Description of the linked file.",
            type="The external service hosting the file (e.g. google, dropbox, box, url).",
            url="URL of the externally hosted file.",
            uploader_id="ID of the member who linked the file.",
            story_ids="IDs of the stories the linked file is attached to.",
        ),
    },
    "repositories": {
        "description": "A version-control repository connected to the Shortcut workspace.",
        "docs_url": "https://developer.shortcut.com/api/rest/v3#Repository",
        "columns": _columns(
            name="The repository's name.",
            full_name="The repository's full name, including its owner.",
            type="The version-control provider (e.g. github).",
            url="URL of the repository.",
            external_id="The provider's identifier for the repository.",
        ),
    },
    "entity_templates": {
        "description": "A reusable template for creating stories with predefined values.",
        "docs_url": "https://developer.shortcut.com/api/rest/v3#EntityTemplate",
        "columns": _columns(
            name="The template's name.",
            author_id="ID of the member who created the template.",
            story_contents="The default story field values applied when the template is used.",
            last_used_at="Time at which the template was last used.",
        ),
    },
    "stories": {
        "description": "A unit of work in Shortcut — a feature, bug, or chore tracked through a workflow.",
        "docs_url": "https://developer.shortcut.com/api/rest/v3#Story",
        "columns": _columns(
            name="The story's title.",
            description="The story's description.",
            story_type="Type of the story (feature, bug, or chore).",
            workflow_state_id="ID of the workflow state the story is currently in.",
            epic_id="ID of the epic the story belongs to, if any.",
            iteration_id="ID of the iteration the story is in, if any.",
            project_id="ID of the project the story belongs to, if any.",
            group_id="ID of the team (group) that owns the story.",
            owner_ids="IDs of the members who own the story.",
            requested_by_id="ID of the member who requested the story.",
            estimate="Point estimate of the story's effort.",
            deadline="The story's due date, if set.",
            labels="Labels applied to the story.",
            started="Whether work on the story has started.",
            completed="Whether the story has been completed.",
            blocked="Whether the story is blocked by another story.",
            started_at="Time at which work on the story started.",
            completed_at="Time at which the story was completed.",
            archived="Whether the story has been archived.",
        ),
    },
}
