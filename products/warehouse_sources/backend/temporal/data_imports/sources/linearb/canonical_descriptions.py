from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "teams": {
        "description": "Teams configured in LinearB, including their hierarchy and membership.",
        "docs_url": "https://docs.linearb.io/api-teams-v2/",
        "columns": {
            "id": "Unique identifier for the team.",
            "organization_id": "Identifier of the organization the team belongs to.",
            "name": "Team name.",
            "created_at": "When the team was created.",
            "initials": "Short initials shown for the team in the UI.",
            "color": "Display color assigned to the team.",
            "parent_id": "Identifier of the parent team, if this team is nested.",
            "contributors": "Contributors that belong to the team.",
        },
    },
    "users": {
        "description": "Users and their cross-platform contributor identity mapping in LinearB.",
        "docs_url": "https://docs.linearb.io/api-users/",
        "columns": {
            "id": "Unique identifier for the user.",
            "organization_id": "Identifier of the organization the user belongs to.",
            "name": "User's display name.",
            "email": "User's email address.",
            "avatar_url": "URL of the user's avatar image.",
            "created_at": "When the user was created.",
            "updated_at": "When the user was last updated.",
            "deleted_at": "When the user was deleted, if applicable.",
            "team_membership": "Teams the user is a member of.",
            "connected_users": "Platform users and contributors linked to this user's identity.",
        },
    },
    "services": {
        "description": "Services configured in LinearB and the repositories and paths mapped to each.",
        "docs_url": "https://docs.linearb.io/api-services/",
        "columns": {
            "id": "Unique identifier for the service.",
            "name": "Service name.",
            "paths": "Repositories and directory paths mapped to the service.",
        },
    },
    "deployments": {
        "description": "Deployments recorded in LinearB, used to compute deploy frequency, change failure rate, and MTTR.",
        "docs_url": "https://docs.linearb.io/api-deployments/",
        "columns": {
            "id": "Unique identifier for the deployment.",
            "repo_url": "Git repository the deployment came from.",
            "ref_name": "Deployed ref (branch or tag).",
            "stage": "Deployment stage/environment (premium feature).",
            "services": "Services associated with the deployment.",
        },
    },
    "measurements": {
        "description": "Organization-level Git/DORA metrics computed by LinearB, rolled up daily.",
        "docs_url": "https://docs.linearb.io/api-measurements-v2/",
        "columns": {
            "after": "Start date (inclusive) of the daily metric window.",
            "before": "End date of the daily metric window.",
            "organization_id": "Identifier of the organization the metrics belong to.",
        },
    },
}
