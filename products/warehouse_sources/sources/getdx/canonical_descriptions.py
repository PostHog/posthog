from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "snapshots": {
        "description": "DX survey snapshots with schedules and response counts.",
        "docs_url": "https://docs.getdx.com/webapi/methods/snapshots.list/",
        "columns": {
            "id": "Snapshot identifier.",
            "scheduled_for": "Date scheduled for the snapshot.",
            "completed_at": "Time when the snapshot completed.",
            "last_result_change_at": "Time of the latest change to the snapshot results.",
            "completed_count": "Number of completed responses.",
            "total_count": "Total number of snapshot participants.",
        },
    },
    "teams": {
        "description": "DX teams with their hierarchy and manager.",
        "docs_url": "https://docs.getdx.com/webapi/methods/teams.list/",
        "columns": {
            "id": "DX team identifier.",
            "name": "Team name.",
            "parent_id": "Identifier of the parent team.",
            "manager_id": "Identifier of the team manager.",
            "reference_id": "Team identifier from the organization.",
        },
    },
    "users": {
        "description": "DX users with roles, custom properties, or membership in teams, groups, or catalog ownership.",
        "docs_url": "https://docs.getdx.com/webapi/methods/users.list/",
        "columns": {
            "id": "DX user identifier.",
            "name": "User display name.",
            "email": "User email address.",
            "roles": "Roles assigned to the user.",
            "attributes": "Custom user attributes, including privileged attributes.",
            "deleted_at": "Time when the user was marked as deleted.",
        },
    },
    "team_audit_events": {
        "description": "Audit events for changes to DX teams.",
        "docs_url": "https://docs.getdx.com/webapi/methods/teams.audittrail/",
        "columns": {
            "id": "Audit event identifier.",
            "actor": "User who made the change.",
            "team": "Name of the affected team.",
            "action": "Type of team change.",
            "metadata": "Details of the change.",
            "created": "Event time in Unix seconds.",
        },
    },
    "scorecards": {
        "description": "Published and draft DX Fabric scorecards with their checks and scoring rules.",
        "docs_url": "https://docs.getdx.com/webapi/methods/scorecards.list/",
        "columns": {
            "id": "Scorecard identifier.",
            "name": "Scorecard name.",
            "type": "Scoring method, such as levels or points.",
            "published": "Whether the scorecard is published.",
            "checks": "Checks defined in the scorecard.",
        },
    },
}
