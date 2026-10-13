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
    "project_members": {
        "description": "Members granted access to a Doppler project: workplace users, groups, service accounts, and pending invites.",
        "docs_url": "https://docs.doppler.com/reference/project_members-list",
        "columns": {
            "project": "Slug of the project the membership belongs to.",
            "type": "Kind of member: `workplace_user`, `group`, `invite`, or `service_account`.",
            "slug": "Identifier for the member, unique within its member type.",
            "role": "The project role the member holds, as an object carrying the role `identifier`.",
            "access_all_environments": "Whether the member can reach every environment in the project.",
            "environments": "Identifiers of the environments the member can reach when access is not project-wide.",
        },
    },
    "project_roles": {
        "description": "Project role definitions available in the workplace, resolving the role identifier carried on project members.",
        "docs_url": "https://docs.doppler.com/reference/project_roles-list",
        "columns": {
            "identifier": "Unique identifier for the role, as referenced by project members.",
            "name": "Human-readable name of the role.",
            "permissions": "Permission slugs the role grants within a project.",
            "is_custom_role": "Whether the role was defined by the workplace rather than supplied by Doppler.",
            "created_at": "When the role was created.",
        },
    },
    "workplace_roles": {
        "description": "Workplace role definitions, resolving the workplace role carried on workplace users, service accounts, and invites.",
        "docs_url": "https://docs.doppler.com/reference/workplace_roles-list",
        "columns": {
            "identifier": "Unique identifier for the role, as referenced by workplace members.",
            "name": "Human-readable name of the role.",
            "permissions": "Permission slugs the role grants across the workplace.",
            "is_custom_role": "Whether the role was defined by the workplace rather than supplied by Doppler.",
            "is_inline_role": "Whether the role is an inline role generated for a single assignment.",
            "created_at": "When the role was created.",
        },
    },
    "config_logs": {
        "description": "Change history for a config, recording each secret edit and rollback. Secret values are not synced.",
        "docs_url": "https://docs.doppler.com/reference/config_logs-list",
        "columns": {
            "id": "Unique identifier for the config log entry.",
            "text": "Plain-text description of the change.",
            "html": "HTML description of the change.",
            "diff": "The secrets the change touched, by name. `added` and `removed` say whether a value was set or cleared. Secret values are not synced.",
            "rollback": "Whether the entry is a rollback of an earlier change.",
            "user": "The user who made the change (email, name, profile image).",
            "project": "Identifier of the project the config belongs to.",
            "environment": "Identifier of the environment the config belongs to.",
            "config": "Name of the config the change was made to.",
            "created_at": "When the change was made.",
        },
    },
}
