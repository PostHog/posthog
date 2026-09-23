"""Canonical, documentation-sourced descriptions for Lovable endpoints and columns.

Sourced from the Lovable API v1 reference (https://api.lovable.dev/v1/docs). Keyed by the resource
names in `settings.py` `LOVABLE_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
Lovable table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://api.lovable.dev/v1/docs"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Workspaces": {
        "description": "A Lovable workspace the API key's owner belongs to, and the container for its projects, members, and credits.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Workspace ID.",
            "name": "Workspace display name.",
            "description": "Workspace description.",
            "plan": "Plan tier: free, pro, business, or enterprise.",
            "num_projects": "Number of projects in the workspace.",
            "image_url": "Workspace image URL.",
            "membership": "The API key owner's membership in this workspace.",
            "created_at": "When the workspace was created.",
            "updated_at": "When the workspace was last updated.",
        },
    },
    "Projects": {
        "description": "An app built in Lovable, listed per workspace.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Project ID.",
            "workspace_id": "Workspace the project belongs to.",
            "user_id": "Project owner user ID.",
            "name": "Project slug.",
            "display_name": "Human-readable project name.",
            "description": "Description supplied by the caller on create or update.",
            "generated_description": "AI-written summary of what the project does. Absent until the agent has completed a response for the project.",
            "project_type": "Project type: project or library.",
            "tech_stack": "Project tech stack.",
            "status": "Provisioning status of the project scaffold, not agent build progress: in_progress, completed, or failed.",
            "visibility": "Project visibility: draft, private, workspace_view, or public.",
            "is_published": "Whether the project is published.",
            "publish_visibility": "Published visibility: public or private.",
            "url": "Published project URL.",
            "folder_id": "Folder the project belongs to, if any.",
            "latest_screenshot_url": "URL of the latest screenshot.",
            "og_image_url": "Open Graph image URL.",
            "last_edited_at": "When the project was last edited.",
            "created_at": "When the project was created.",
            "updated_at": "When the project was last updated.",
        },
    },
    "WorkspaceMembers": {
        "description": "A member of a Lovable workspace, including pending invites.",
        "docs_url": _DOCS_URL,
        "columns": {
            "workspace_id": "Workspace the membership belongs to.",
            "user_id": "Stable identifier for the entry: the user ID for active members, the membership row ID for pending invites.",
            "display_name": "User display name as stored on the membership.",
            "email": "Member email as stored on the membership. For pending invites this is the invited email.",
            "role": "Workspace role: owner, admin, member, viewer, or collaborator.",
            "monthly_credit_limit": "Explicit monthly credit cap for this member. Absent when the workspace default applies.",
            "invited_at": "When the user was invited.",
            "joined_at": "When the user accepted the invitation. Absent on pending invites.",
        },
    },
    "WorkspaceCreditHistory": {
        "description": "One entry in a workspace's credit ledger: a grant, expiry, adjustment, or conversion.",
        "docs_url": _DOCS_URL,
        "columns": {
            "workspace_id": "Workspace the entry belongs to.",
            "id": "Stable ledger entry ID.",
            "credits_change": "Signed change in Lovable credits: positive for grants, negative for expiries and debits.",
            "event_type": "What happened to the credits.",
            "grant_type": "Credit bucket this entry affected.",
            "label": "Human-readable summary of the entry.",
            "occurred_at": "When the entry occurred.",
        },
    },
    "ProjectCollaborators": {
        "description": "A user with direct access to one project, whether or not they are a member of its workspace.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project_id": "Project the access grant belongs to.",
            "workspace_id": "Workspace the project belongs to.",
            "user_id": "User ID of the collaborator.",
            "display_name": "Display name, falling back to the email when the user has not set one.",
            "email": "Email address of the collaborator.",
            "access_level": "Access level: owner, admin, write, or read.",
            "is_workspace_member": "Whether the collaborator is a member of the project's workspace. False marks an ad-hoc collaborator with no broader workspace access.",
            "is_internal": "Whether the collaborator is internal to the workspace, by membership or by a workspace-verified email domain.",
            "invited_by": "User ID of the inviter. Empty for the project owner.",
            "invited_at": "When the user was invited to the project. Null for the project owner.",
            "accepted_at": "When the user accepted the project invitation. Null while the invite is pending.",
        },
    },
    "ProjectSecurityScans": {
        "description": "One security scan invocation against a project.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project_id": "Project that was scanned.",
            "workspace_id": "Workspace the project belongs to.",
            "scan_id": "Unique scan invocation ID.",
            "status": "Scan status: running, completed, or failed.",
            "trigger_source": "What triggered the scan, such as workflow, user, ui_auto, or workspace_scheduled.",
            "triggered_by": "Actor that triggered the scan.",
            "requested_scanners": "Scanners requested for this invocation.",
            "commit_sha": "Project commit at scan start.",
            "started_at": "When the scan started.",
            "finished_at": "When the scan finished.",
        },
    },
    "ProjectPiiLabels": {
        "description": "A piece of personal data Lovable's scanners detected in a project.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project_id": "Project the label belongs to.",
            "workspace_id": "Workspace the project belongs to.",
            "id": "PII label ID.",
            "source": "Where the PII was detected: chat, upload, cloud_storage, or cloud_sql.",
            "info_type": "DLP info type, such as EMAIL_ADDRESS.",
            "likelihood": "DLP likelihood: VERY_UNLIKELY, UNLIKELY, POSSIBLE, LIKELY, or VERY_LIKELY.",
            "sensitivity": "Sensitivity bucket: low, mid, or high.",
            "status": "Label status: open, ignored, or fixed.",
            "quote": "Masked sample of the detected value.",
            "scan_id": "Scan run that recorded the label.",
            "chat_message_id": "Trajectory event ID, for chat-source labels.",
            "chat_upload_id": "Uploaded file ID, for upload-source labels.",
            "connector_id": "Connector ID, for connector labels.",
            "sql_location": "Database location, for cloud_sql labels.",
            "storage_path": "Cloud storage object path, for cloud_storage labels.",
            "found_at": "When the label was recorded.",
        },
    },
}
