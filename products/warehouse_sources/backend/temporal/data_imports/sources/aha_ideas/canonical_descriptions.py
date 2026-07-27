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
}
