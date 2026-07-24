from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "A Doppler project, the top-level grouping of environments and configs for an application or service.",
        "docs_url": "https://docs.doppler.com/reference/projects-list",
        "columns": {
            "id": "Unique identifier for the project.",
            "slug": "URL-safe identifier for the project, used as the `project` parameter in API calls.",
            "name": "Human-readable name of the project.",
            "description": "Description of the project.",
            "created_at": "When the project was created.",
        },
    },
    "environments": {
        "description": "An environment within a Doppler project (e.g. development, staging, production).",
        "docs_url": "https://docs.doppler.com/reference/environments-list",
        "columns": {
            "id": "Identifier for the environment, unique within its project (e.g. `dev`, `stg`, `prd`).",
            "name": "Human-readable name of the environment.",
            "project": "Identifier of the project the environment belongs to.",
            "initial_fetch_at": "When secrets were first fetched from an environment config.",
            "created_at": "When the environment was created.",
        },
    },
    "configs": {
        "description": "A config within a Doppler project environment, holding a set of secrets. Secret values are not synced.",
        "docs_url": "https://docs.doppler.com/reference/configs-list",
        "columns": {
            "name": "Name of the config, unique within its project.",
            "project": "Identifier of the project the config belongs to.",
            "environment": "Identifier of the environment the config belongs to.",
            "root": "Whether this is the environment's root config (branch configs are non-root).",
            "locked": "Whether the config is locked against deletion.",
            "initial_fetch_at": "When secrets were first fetched from this config.",
            "last_fetch_at": "When secrets were last fetched from this config.",
            "created_at": "When the config was created.",
        },
    },
    "activity_logs": {
        "description": "Workplace activity log entries recording project, config, secret, and access changes.",
        "docs_url": "https://docs.doppler.com/reference/activity_logs-list",
        "columns": {
            "id": "Unique identifier for the activity log entry.",
            "text": "Plain-text description of the activity.",
            "html": "HTML description of the activity.",
            "project": "Identifier of the project the activity relates to, if any.",
            "environment": "Identifier of the environment the activity relates to, if any.",
            "config": "Name of the config the activity relates to, if any.",
            "user": "The user who performed the activity (email, name, profile image).",
            "created_at": "When the activity occurred.",
        },
    },
    "workplace_users": {
        "description": "Users belonging to the Doppler workplace, with their workplace-level access role.",
        "docs_url": "https://docs.doppler.com/reference/users-list",
        "columns": {
            "id": "Unique identifier for the workplace user.",
            "access": "The user's workplace access role (e.g. `owner`, `admin`, `collaborator`).",
            "user": "The user's account details (email, name, username, profile image).",
            "created_at": "When the user joined the workplace.",
        },
    },
    "groups": {
        "description": "User groups in the Doppler workplace, used to manage project access in bulk.",
        "docs_url": "https://docs.doppler.com/reference/groups-list",
        "columns": {
            "slug": "Unique identifier for the group.",
            "name": "Name of the group.",
            "default_project_role": "The project role members of this group receive by default.",
            "created_at": "When the group was created.",
        },
    },
    "service_accounts": {
        "description": "Machine identities in the Doppler workplace used for programmatic access.",
        "docs_url": "https://docs.doppler.com/reference/service_accounts-list",
        "columns": {
            "slug": "Unique identifier for the service account.",
            "name": "Name of the service account.",
            "workplace_role": "The service account's workplace role and permissions.",
            "created_at": "When the service account was created.",
        },
    },
    "invites": {
        "description": "Pending invitations to join the Doppler workplace.",
        "docs_url": "https://docs.doppler.com/reference/invites-list",
        "columns": {
            "slug": "Unique identifier for the invite.",
            "email": "Email address the invite was sent to.",
            "workplace_role": "The workplace role the invitee will receive on acceptance.",
            "created_at": "When the invite was sent.",
        },
    },
}
