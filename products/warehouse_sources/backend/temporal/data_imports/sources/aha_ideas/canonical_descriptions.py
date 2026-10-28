"""Canonical, documentation-sourced descriptions for Aha! Ideas endpoints and columns.

Sourced from the official Aha! API reference (https://www.aha.io/api/resources/ideas). Keyed by the
endpoint names in `settings.py` `AHA_IDEAS_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Aha! Ideas table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "ideas": {
        "description": "An idea submitted to your Aha! Ideas portal — feedback that can be promoted into features.",
        "docs_url": "https://www.aha.io/api/resources/ideas/list_ideas",
        "columns": {
            "id": "Unique identifier for the idea.",
            "name": "The idea's name.",
            "reference_num": "Human-readable reference number (e.g. PRJ1-I-1).",
            "created_at": "Time at which the idea was created.",
            "updated_at": "Time at which the idea was last updated.",
            "workflow_status": "The idea's current status in its workflow.",
            "url": "URL of the idea in the Aha! web app.",
            "resource": "API URL of the idea.",
        },
    },
    "idea_portals": {
        "description": "An Aha! Ideas portal — a public or private site where users submit and vote on ideas.",
        "docs_url": "https://www.aha.io/api/resources/idea_portals/list_all_idea_portals_in_an_account",
        "columns": {
            "id": "Unique identifier for the idea portal.",
            "title": "The portal's display name.",
            "portal_enabled": "Whether the portal is currently enabled.",
            "access_type": "Who can access the portal (e.g. public, submit-only).",
            "external_url": "Public URL of the portal.",
            "created_at": "Time at which the portal was created.",
        },
    },
    "idea_organizations": {
        "description": "A submitting organization associated with idea votes — typically a customer account.",
        "docs_url": "https://www.aha.io/api/resources/idea_organizations/list_idea_organizations",
        "columns": {
            "id": "Unique identifier for the idea organization.",
            "name": "The organization's name.",
            "created_at": "Time at which the organization was created.",
            "url": "URL of the organization in the Aha! web app.",
            "resource": "API URL of the organization.",
        },
    },
    "idea_users": {
        "description": "An external user who has submitted ideas or votes to your Aha! Ideas portals.",
        "docs_url": "https://www.aha.io/api/resources/idea_users/list_idea_users_for_an_account",
        "columns": {
            "id": "Unique identifier for the idea user.",
            "name": "The idea user's full name.",
            "email": "The idea user's email address.",
            "created_at": "Time at which the idea user was created.",
        },
    },
    "idea_themes": {
        "description": "A theme grouping related ideas together by topic.",
        "docs_url": "https://www.aha.io/api/resources/idea_themes/list_idea_themes",
        "columns": {
            "id": "Unique identifier for the theme.",
            "reference_num": "Human-readable reference number for the theme.",
            "name": "The theme's name.",
            "created_at": "Time at which the theme was created.",
        },
    },
    "idea_endorsements": {
        "description": "A vote (endorsement) cast for an idea, optionally by a portal user and/or organization.",
        "docs_url": "https://www.aha.io/api/resources/idea_votes/list_votes_for_an_account",
        "columns": {
            "id": "Unique identifier for the vote.",
            "idea_id": "Identifier of the idea this vote was cast for.",
            "created_at": "Time at which the vote was created.",
            "updated_at": "Time at which the vote was last updated.",
            "value": "Custom point value assigned to the vote, if any.",
            "weight": "Number of votes this record counts as (proxy votes can count for more than one).",
            "endorsed_by_portal_user": "The ideas portal user who cast the vote, if submitted via a portal.",
            "endorsed_by_idea_user": "The idea user who cast the vote.",
            "idea_organization": "The organization the voter belongs to, if any.",
        },
    },
    "idea_comments": {
        "description": "A comment left on an idea, by either an internal Aha! user or an ideas portal user.",
        "docs_url": "https://www.aha.io/api/resources/idea_comments/list_idea_comments_for_an_idea",
        "columns": {
            "id": "Unique identifier for the comment.",
            "idea_id": "Identifier of the idea this comment was left on.",
            "body": "The comment's text content.",
            "created_at": "Time at which the comment was created.",
            "updated_at": "Time at which the comment was last updated.",
            "visibility": "Who can see the comment (e.g. visible to all ideas portal users).",
            "parent_idea_comment_id": "Identifier of the parent comment, if this is a reply.",
            "idea_commenter_user": "The user who wrote the comment.",
        },
    },
    "products": {
        "description": "A workspace (product) in your Aha! account. Ideas belong to a workspace through `product_id`.",
        "docs_url": "https://www.aha.io/api/resources/products/list_products_in_the_account",
        "columns": {
            "id": "Unique identifier for the workspace.",
            "reference_prefix": "Prefix used in the reference numbers of the workspace's records.",
            "name": "The workspace's name.",
            "product_line": "Whether this record is a workspace line that groups other workspaces.",
            "workspace_type": "The kind of workspace (e.g. product_workspace).",
            "created_at": "Time at which the workspace was created.",
            "url": "URL of the workspace in the Aha! web app.",
        },
    },
    "users": {
        "description": "A member of your Aha! account, such as an idea assignee or creator.",
        "docs_url": "https://www.aha.io/api/resources/users/list_users",
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "The user's full name.",
            "email": "The user's email address.",
            "created_at": "Time at which the user was created.",
            "updated_at": "Time at which the user was last updated.",
            "accessed_at": "Time at which the user last accessed Aha!.",
            "enabled": "Whether the user can sign in to the account.",
            "product_roles": "The user's role in each workspace.",
        },
    },
    "workflows": {
        "description": "A workflow used by a workspace, with its ordered statuses. Decodes the workflow statuses on ideas.",
        "docs_url": "https://www.aha.io/api/resources/workflows/list_workflows",
        "columns": {
            "id": "Unique identifier for the workflow.",
            "product_id": "Identifier of the workspace this workflow was listed for.",
            "name": "The workflow's name.",
            "statusable_type": "The record type that uses this workflow (e.g. Idea, Feature).",
            "transitions_only": "Whether records can only move between statuses through defined transitions.",
            "workflow_statuses": "The workflow's statuses, with name, position, completion flag and status category.",
        },
    },
    "workflow_status_times": {
        "description": "A period an idea spent in one workflow status. Use it to measure time in status.",
        "docs_url": "https://www.aha.io/api/resources/workflow_status_times/list_workflow_status_times_for_an_idea",
        "columns": {
            "idea_id": "Identifier of the idea.",
            "idea_updated_at": "Time at which the idea was last updated.",
            "status_id": "Identifier of the workflow status.",
            "status_name": "Name of the workflow status.",
            "started_at": "Time at which the idea entered the status.",
            "ended_at": "Time at which the idea left the status. Empty while the idea is still in it.",
        },
    },
}
