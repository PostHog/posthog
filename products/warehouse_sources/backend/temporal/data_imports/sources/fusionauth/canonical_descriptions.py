from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Users": {
        "description": "FusionAuth user accounts, including their registrations, contact info, and account timestamps.",
        "docs_url": "https://fusionauth.io/docs/apis/users",
        "columns": {
            "id": "Unique identifier for the user.",
            "email": "The user's email address.",
            "username": "The user's username.",
            "active": "Whether the user's account is active (not soft-deleted).",
            "insertInstant": "The instant (epoch milliseconds) the user was created.",
            "lastUpdateInstant": "The instant (epoch milliseconds) the user was last updated.",
            "lastLoginInstant": "The instant (epoch milliseconds) of the user's last successful login.",
            "verified": "Whether the user's email address has been verified.",
            "tenantId": "The unique identifier of the tenant the user belongs to.",
            "registrations": "The applications this user is registered for.",
        },
    },
    "AuditLogs": {
        "description": "Administrative actions taken in the FusionAuth admin UI or API, such as user or configuration changes.",
        "docs_url": "https://fusionauth.io/docs/apis/audit-logs",
        "columns": {
            "id": "Unique identifier for the audit log entry.",
            "insertInstant": "The instant (epoch milliseconds) the audit log entry was created.",
            "insertUser": "The email address (or identifier) of the user who performed the action.",
            "message": "A description of the action that was performed.",
            "tenantId": "The unique identifier of the tenant the action was performed in, if applicable.",
            "data": "Additional structured data about the change, such as reason and old/new values.",
        },
    },
    "EventLogs": {
        "description": "Internal FusionAuth system events, such as errors and informational/debug messages.",
        "docs_url": "https://fusionauth.io/docs/apis/event-logs",
        "columns": {
            "id": "Unique identifier for the event log entry.",
            "insertInstant": "The instant (epoch milliseconds) the event log entry was created.",
            "message": "The event log message.",
            "type": "The severity of the event log entry (Information, Debug, or Error).",
        },
    },
    "LoginRecords": {
        "description": "A record of every successful and failed login attempt against a FusionAuth application.",
        "docs_url": "https://fusionauth.io/docs/apis/login",
        "columns": {
            "applicationId": "The unique identifier of the application the login attempt was made against.",
            "applicationName": "The name of the application the login attempt was made against.",
            "userId": "The unique identifier of the user who attempted to log in.",
            "loginId": "The identifier (email or username) the user logged in with.",
            "instant": "The instant (epoch milliseconds) the login attempt occurred.",
            "ipAddress": "The IP address the login attempt was made from.",
        },
    },
    "Applications": {
        "description": "FusionAuth applications that users register for and log in to, with their roles and configuration.",
        "docs_url": "https://fusionauth.io/docs/apis/applications",
        "columns": {
            "id": "Unique identifier for the application.",
            "name": "The name of the application.",
            "tenantId": "The unique identifier of the tenant the application belongs to.",
            "active": "Whether the application is active.",
            "state": "The state of the application (Active or Inactive).",
            "roles": "The roles defined for the application.",
            "insertInstant": "The instant (epoch milliseconds) the application was created.",
            "lastUpdateInstant": "The instant (epoch milliseconds) the application was last updated.",
        },
    },
    "Tenants": {
        "description": "FusionAuth tenants, the top-level isolation boundary for users, applications and groups.",
        "docs_url": "https://fusionauth.io/docs/apis/tenants",
        "columns": {
            "id": "Unique identifier for the tenant.",
            "name": "The name of the tenant.",
            "issuer": "The named issuer used to sign tokens issued for this tenant.",
            "state": "The state of the tenant (Active or PendingDelete).",
            "insertInstant": "The instant (epoch milliseconds) the tenant was created.",
            "lastUpdateInstant": "The instant (epoch milliseconds) the tenant was last updated.",
        },
    },
    "Groups": {
        "description": "FusionAuth groups that users can be members of, each granting a set of application roles.",
        "docs_url": "https://fusionauth.io/docs/apis/groups",
        "columns": {
            "id": "Unique identifier for the group.",
            "name": "The name of the group.",
            "tenantId": "The unique identifier of the tenant the group belongs to.",
            "roles": "The application roles granted to members of the group, keyed by application id.",
            "insertInstant": "The instant (epoch milliseconds) the group was created.",
            "lastUpdateInstant": "The instant (epoch milliseconds) the group was last updated.",
        },
    },
    "GroupMembers": {
        "description": "Memberships linking FusionAuth users to groups.",
        "docs_url": "https://fusionauth.io/docs/apis/groups",
        "columns": {
            "id": "Unique identifier for the group membership.",
            "groupId": "The unique identifier of the group.",
            "userId": "The unique identifier of the user who is a member of the group.",
            "data": "Custom data stored on the membership.",
            "insertInstant": "The instant (epoch milliseconds) the user was added to the group.",
        },
    },
}
