from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Snyk REST API reference (https://apidocs.snyk.io/). Rows are the
# JSON:API record with its `attributes` flattened to the root; fan-out tables additionally carry
# the injected `organization_id`.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "organizations": {
        "description": "A Snyk organization the API token can access. Organizations group projects, targets, and issues, and carry their own settings and membership.",
        "docs_url": "https://apidocs.snyk.io/#get-/orgs",
        "columns": {
            "id": "Unique identifier (UUID) of the organization.",
            "type": "JSON:API resource type (org).",
            "name": "Display name of the organization.",
            "slug": "URL-friendly unique name of the organization.",
            "group_id": "Identifier of the Snyk group the organization belongs to, if any.",
            "is_personal": "Whether the organization is a personal organization rather than a shared one.",
            "created_at": "When the organization was created.",
            "updated_at": "When the organization was last updated.",
        },
    },
    "projects": {
        "description": "A project scanned by Snyk within an organization — one entry per manifest, container image, or IaC configuration monitored for vulnerabilities.",
        "docs_url": "https://apidocs.snyk.io/#get-/orgs/-org_id-/projects",
        "columns": {
            "id": "Unique identifier (UUID) of the project.",
            "type": "JSON:API resource type (project).",
            "organization_id": "Identifier of the organization the project belongs to.",
            "name": "Name of the project, typically the repository plus the manifest path.",
            "origin": "Integration the project was imported from (e.g. github, cli, docker-hub).",
            "target_file": "Path of the scanned manifest or configuration file.",
            "target_reference": "Reference within the target, such as a branch name or image tag.",
            "created": "When the project was created in Snyk.",
            "status": "Whether the project is actively monitored (active) or deactivated (inactive).",
            "business_criticality": "User-assigned business criticality attributes for the project.",
            "environment": "User-assigned environment attributes for the project.",
            "lifecycle": "User-assigned lifecycle stage attributes for the project.",
            "tags": "User-assigned key/value tags on the project.",
        },
    },
    "targets": {
        "description": "A target is the scanned entity a project comes from — a code repository, container image, or other importable asset within an organization.",
        "docs_url": "https://apidocs.snyk.io/#get-/orgs/-org_id-/targets",
        "columns": {
            "id": "Unique identifier (UUID) of the target.",
            "type": "JSON:API resource type (target).",
            "organization_id": "Identifier of the organization the target belongs to.",
            "display_name": "Human-readable name of the target, such as owner/repository.",
            "url": "URL of the target, e.g. the repository or registry location.",
            "is_private": "Whether the target is private in its source system.",
            "created_at": "When the target was created in Snyk.",
        },
    },
    "issues": {
        "description": "A vulnerability, license, or configuration issue found by Snyk in an organization's projects — the core findings table for tracking security backlog, severity mix, and remediation over time.",
        "docs_url": "https://apidocs.snyk.io/#get-/orgs/-org_id-/issues",
        "columns": {
            "id": "Unique identifier (UUID) of the issue.",
            "type": "JSON:API resource type (issue).",
            "organization_id": "Identifier of the organization the issue belongs to.",
            "key": "Stable key identifying the issue across scans.",
            "title": "Human-readable title of the issue.",
            "effective_severity_level": "Effective severity of the issue (low, medium, high, critical) after any user overrides.",
            "status": "Current status of the issue (open or resolved).",
            "ignored": "Whether the issue has been ignored.",
            "problems": "The underlying problems (vulnerabilities or license conditions) that cause the issue.",
            "coordinates": "Where the issue was found, including the affected package or resource and remediation availability.",
            "classes": "Weakness classes for the issue, such as CWE identifiers.",
            "risk": "Risk information for the issue, including the Snyk risk score when available.",
            "created_at": "When the issue was first created.",
            "updated_at": "When the issue was last updated.",
        },
    },
    "org_memberships": {
        "description": "A user's membership of a Snyk organization, with the role the user holds in that organization.",
        "docs_url": "https://apidocs.snyk.io/#get-/orgs/-org_id-/memberships",
        "columns": {
            "id": "Unique identifier (UUID) of the membership.",
            "type": "JSON:API resource type (org_membership).",
            "organization_id": "Identifier of the organization the membership belongs to.",
            "created_at": "When the user became a member of the organization.",
            "relationships": "The organization, the user (id, name, email, username, login method) and the role (id, name) of the membership.",
        },
    },
    "group_memberships": {
        "description": "A user's membership of a Snyk group, with the group-level role the user holds. A group is the parent of a set of organizations.",
        "docs_url": "https://apidocs.snyk.io/#get-/groups/-group_id-/memberships",
        "columns": {
            "id": "Unique identifier (UUID) of the membership.",
            "type": "JSON:API resource type (group_membership).",
            "group_id": "Identifier of the group the membership belongs to.",
            "created_at": "When the user became a member of the group.",
            "meta": "Membership metadata, such as the number of group memberships the user has.",
            "relationships": "The group, the user (id, name, email, username, login method) and the role (id, name) of the membership.",
        },
    },
    "collections": {
        "description": "A collection is a named set of projects in an organization, used to group projects for reporting.",
        "docs_url": "https://apidocs.snyk.io/#get-/orgs/-org_id-/collections",
        "columns": {
            "id": "Unique identifier (UUID) of the collection.",
            "type": "JSON:API resource type (collection).",
            "organization_id": "Identifier of the organization the collection belongs to.",
            "name": "Name of the collection.",
            "is_generated": "Whether Snyk generated the collection rather than a user.",
            "meta": "Counts for the collection: projects and issues by severity (critical, high, medium, low).",
            "relationships": "The organization of the collection and the user who created it.",
        },
    },
    "collection_projects": {
        "description": "One row for each project in a collection. A project can be in more than one collection.",
        "docs_url": "https://apidocs.snyk.io/#get-/orgs/-org_id-/collections/-collection_id-/relationships/projects",
        "columns": {
            "id": "Identifier (UUID) of the project.",
            "type": "JSON:API resource type (project).",
            "collection_id": "Identifier of the collection that contains the project.",
            "organization_id": "Identifier of the organization the collection belongs to.",
            "meta": "Project data: when it was imported, when it was last tested, and its issue counts by severity.",
            "relationships": "The target the project was imported from.",
        },
    },
}
