"""Canonical, documentation-sourced descriptions for SingleStore Management API endpoints.

Sourced from the official Management API overview and reference
(https://docs.singlestore.com/cloud/reference/management-api/) plus the field names confirmed
against SingleStore's own `singlestoredb-python` SDK source. Keyed by the resource names in
`settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced table. Columns
absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "organization": {
        "description": "The SingleStore Helios organization the API key belongs to.",
        "docs_url": "https://docs.singlestore.com/cloud/reference/management-api/",
        "columns": {
            "orgID": "Unique identifier of the organization.",
            "name": "Name of the organization.",
            "firewallRanges": "IP ranges allowed to connect to the organization's resources.",
        },
    },
    "regions": {
        "description": "A cloud region SingleStore Helios can deploy workspace groups into.",
        "docs_url": "https://docs.singlestore.com/cloud/reference/management-api/",
        "columns": {
            "regionID": "Unique identifier of the region.",
            "region": "Human-readable name of the region.",
            "provider": "Cloud provider hosting the region (AWS, GCP, or Azure).",
            "regionName": "Provider-specific region name (e.g. us-east-1).",
        },
    },
    "workspace_groups": {
        "description": "A SingleStore Helios workspace group — the deployment unit that holds one "
        "or more workspaces sharing storage, networking, and region.",
        "docs_url": "https://docs.singlestore.com/cloud/reference/management-api/",
        "columns": {
            "workspaceGroupID": "Unique identifier of the workspace group.",
            "name": "Name of the workspace group.",
            "createdAt": "Time the workspace group was created.",
            "terminatedAt": "Time the workspace group was terminated, if applicable.",
            "regionID": "Identifier of the region the workspace group is deployed in.",
            "firewallRanges": "IP ranges allowed to connect to workspaces in this group.",
            "allowAllTraffic": "Whether inbound traffic from any IP address is allowed.",
        },
    },
    "workspaces": {
        "description": "A SingleStore Helios workspace — a compute cluster within a workspace "
        "group that runs queries against the group's shared storage.",
        "docs_url": "https://docs.singlestore.com/cloud/reference/management-api/",
        "columns": {
            "workspaceID": "Unique identifier of the workspace.",
            "workspaceGroupID": "Identifier of the workspace group this workspace belongs to.",
            "name": "Name of the workspace.",
            "size": "Workspace size in SingleStore size notation (e.g. S-00, S-1).",
            "state": "Current state of the workspace (e.g. ACTIVE, SUSPENDED, RESUMING).",
            "createdAt": "Time the workspace was created.",
            "terminatedAt": "Time the workspace was terminated, if applicable.",
            "endpoint": "Hostname used to connect to the workspace's database server.",
            "cacheConfig": "Multiplier applied to the workspace's persistent cache.",
            "deploymentType": "Deployment type of the workspace (PRODUCTION or NON-PRODUCTION).",
        },
    },
    "billing_usage": {
        "description": "Compute credit and storage usage for the organization, broken down by "
        "resource and time window.",
        "docs_url": "https://docs.singlestore.com/cloud/reference/management-api/",
        "columns": {
            "metric": "Usage metric this row measures (compute credits or average storage bytes).",
            "description": "Human-readable description of the metric.",
            "startTime": "Start of the usage interval this row covers.",
            "endTime": "End of the usage interval this row covers.",
            "resourceName": "Name of the resource (e.g. workspace) the usage is attributed to.",
            "value": "Usage value for the metric over this interval.",
        },
    },
    "projects": {
        "description": "A SingleStore Helios project, which groups the organization's database resources.",
        "docs_url": "https://docs.singlestore.com/cloud/reference/management-api/reference/",
        "columns": {
            "projectID": "Unique identifier of the project.",
            "name": "Name of the project.",
            "edition": "Edition of the project (STANDARD, ENTERPRISE, PREMIUM, DEDICATED, or SHARED).",
            "createdAt": "Time the project was created.",
        },
    },
    "starter_clusters": {
        "description": "A Shared Edition deployment (starter cluster). These are not listed with "
        "the organization's workspaces.",
        "docs_url": "https://docs.singlestore.com/cloud/reference/management-api/reference/",
        "columns": {
            "virtualClusterID": "Unique identifier of the starter cluster.",
            "name": "Name of the starter cluster.",
            "projectID": "Identifier of the project the starter cluster is assigned to.",
            "databaseName": "Name of the starter cluster's database.",
            "endpoint": "Application endpoint used to connect to the database.",
            "mysqlDmlPort": "MySQL DML port of the endpoint.",
            "websocketPort": "WebSocket port of the endpoint.",
        },
    },
    "audit_logs": {
        "description": "A Control Plane audit log entry that records an action in the organization.",
        "docs_url": "https://docs.singlestore.com/cloud/reference/management-api/reference/",
        "columns": {
            "auditID": "Unique identifier of the audit log entry.",
            "createdAt": "Time the entry was created, in RFC3339Nano format.",
            "type": "Type of the audit log entry (e.g. Login).",
            "source": "Source of the entry (Portal, Admin, or SystemJob).",
            "reason": "Human-readable description of what happened.",
            "error": "Error message related to the entry, if any.",
            "labels": "Audit keywords for the entry.",
            "attributes": "Additional keys and values specific to the entry type.",
            "orgID": "Identifier of the organization tied to the event.",
            "userID": "Identifier of the user who performed the action.",
            "userEmail": "Email address of the user.",
            "userType": "Type of user that triggered the entry (e.g. Customer, System, Automation).",
            "apiKeyID": "Identifier of the API key used to perform the action, if applicable.",
            "sessionID": "Identifier of the authorization session tied to the event.",
            "clusterID": "Identifier of the database cluster tied to the event.",
            "workspaceID": "Identifier of the workspace tied to the event.",
            "teamID": "Identifier of the team related to the event.",
            "projectID": "Deprecated internal project identifier, not related to the projects table.",
            "firstName": "First name of a redacted user.",
            "lastName": "Last name of a redacted user.",
        },
    },
}
