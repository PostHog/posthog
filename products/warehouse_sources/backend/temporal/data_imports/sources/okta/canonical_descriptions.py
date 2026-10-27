"""Canonical, documentation-sourced descriptions for Okta endpoints and columns.

Sourced from the official Okta Management API reference (https://developer.okta.com/docs/api/).
Keyed by the endpoint names in `settings.py` `OKTA_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Okta table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "users": {
        "description": "An Okta user account, with profile, credentials, and lifecycle status.",
        "docs_url": "https://developer.okta.com/docs/reference/api/users/",
        "columns": {
            "id": "Unique identifier for the user.",
            "status": "Lifecycle status of the user (e.g. ACTIVE, STAGED, PROVISIONED, SUSPENDED, DEPROVISIONED).",
            "profile": "User profile attributes (login, email, firstName, lastName, etc.).",
            "credentials": "Authentication credentials and recovery configuration for the user.",
            "type": "Reference to the user type that defines the profile schema.",
            "created": "Time at which the user was created.",
            "activated": "Time at which the user was activated.",
            "statusChanged": "Time at which the user's status last changed.",
            "lastLogin": "Time of the user's most recent successful login.",
            "lastUpdated": "Time at which the user was last updated.",
            "passwordChanged": "Time at which the user's password was last changed.",
        },
    },
    "groups": {
        "description": "An Okta group used to manage membership and assign apps and policies.",
        "docs_url": "https://developer.okta.com/docs/reference/api/groups/",
        "columns": {
            "id": "Unique identifier for the group.",
            "type": "Type of group: OKTA_GROUP, APP_GROUP, or BUILT_IN.",
            "profile": "Group profile attributes (name and description).",
            "objectClass": "Object classes that define the group's profile schema.",
            "created": "Time at which the group was created.",
            "lastUpdated": "Time at which the group was last updated.",
            "lastMembershipUpdated": "Time at which the group's membership last changed.",
        },
    },
    "applications": {
        "description": "An application integrated with Okta for single sign-on and provisioning.",
        "docs_url": "https://developer.okta.com/docs/reference/api/apps/",
        "columns": {
            "id": "Unique identifier for the application.",
            "name": "Internal name (key) of the application.",
            "label": "User-facing display name of the application.",
            "status": "Status of the application: ACTIVE or INACTIVE.",
            "signOnMode": "Authentication scheme used by the app (e.g. SAML_2_0, OPENID_CONNECT, AUTO_LOGIN).",
            "features": "Enabled features for the application (e.g. provisioning).",
            "settings": "Configuration settings for the application.",
            "created": "Time at which the application was created.",
            "lastUpdated": "Time at which the application was last updated.",
        },
    },
    "logs": {
        "description": "System Log events — the audit trail of actions and authentication events in the Okta org.",
        "docs_url": "https://developer.okta.com/docs/reference/api/system-log/",
        "columns": {
            "uuid": "Unique identifier for the log event.",
            "published": "Time at which the event was published.",
            "eventType": "Type of the event (e.g. user.session.start).",
            "displayMessage": "Human-readable description of the event.",
            "severity": "Severity of the event: DEBUG, INFO, WARN, or ERROR.",
            "outcome": "Outcome of the event, including result (SUCCESS, FAILURE) and reason.",
            "actor": "The entity (user, app, or system) that performed the action.",
            "client": "Client details (IP, user agent, geographical context) for the event.",
            "target": "The objects the action was performed against.",
            "transaction": "Transaction details linking related events.",
        },
    },
    "group_rules": {
        "description": "A rule that automatically assigns users to Okta groups based on conditions.",
        "docs_url": "https://developer.okta.com/docs/reference/api/groups/#group-rule-operations",
        "columns": {
            "id": "Unique identifier for the group rule.",
            "name": "The group rule's name.",
            "type": "Type of the group rule.",
            "status": "Status of the rule: ACTIVE or INACTIVE.",
            "conditions": "Conditions (expression and people scope) that trigger the rule.",
            "actions": "Actions applied when the rule matches, such as target group assignments.",
            "created": "Time at which the rule was created.",
            "lastUpdated": "Time at which the rule was last updated.",
        },
    },
    "user_types": {
        "description": "A user type that defines the profile schema available to Okta users.",
        "docs_url": "https://developer.okta.com/docs/reference/api/user-types/",
        "columns": {
            "id": "Unique identifier for the user type.",
            "name": "Internal name of the user type.",
            "displayName": "User-facing display name of the user type.",
            "description": "Description of the user type.",
            "default": "Whether this is the default user type for the org.",
            "created": "Time at which the user type was created.",
            "lastUpdated": "Time at which the user type was last updated.",
        },
    },
    "group_members": {
        "description": "Group membership: one row per user in each Okta group. Joins the users and groups tables.",
        "docs_url": "https://developer.okta.com/docs/api/openapi/okta-management/management/tag/Group/#tag/Group/operation/listGroupUsers",
        "columns": {
            "group_id": "Identifier of the group the user belongs to.",
            "id": "Unique identifier of the member user.",
            "status": "Lifecycle status of the member user.",
            "profile": "Profile attributes of the member user.",
            "created": "Time at which the member user was created.",
            "lastUpdated": "Time at which the member user was last updated.",
        },
    },
    "application_users": {
        "description": "Application assignments: one row per user assigned to each Okta application.",
        "docs_url": "https://developer.okta.com/docs/api/openapi/okta-management/management/tag/ApplicationUsers/#tag/ApplicationUsers/operation/listApplicationUsers",
        "columns": {
            "app_id": "Identifier of the application the user is assigned to.",
            "id": "Unique identifier of the assigned user.",
            "scope": "How the user is assigned: USER (directly) or GROUP (through a group assignment).",
            "status": "Status of the app user (e.g. ACTIVE, PROVISIONED, DEPROVISIONED).",
            "syncState": "Synchronization state of the app user when provisioning is enabled.",
            "credentials": "The user's credentials for the application, such as the app username.",
            "profile": "App-specific profile attributes of the user.",
            "externalId": "Identifier of the user in the application, when provisioning is enabled.",
            "created": "Time at which the user was assigned to the application.",
            "lastUpdated": "Time at which the assignment was last updated.",
            "statusChanged": "Time at which the app user's status last changed.",
            "lastSync": "Time of the last synchronization with the application.",
            "passwordChanged": "Time at which the app password was last changed.",
        },
    },
    "application_groups": {
        "description": "Group-based application assignments: one row per group assigned to each Okta application.",
        "docs_url": "https://developer.okta.com/docs/api/openapi/okta-management/management/tag/ApplicationGroups/#tag/ApplicationGroups/operation/listApplicationGroupAssignments",
        "columns": {
            "app_id": "Identifier of the application the group is assigned to.",
            "id": "Unique identifier of the assigned group.",
            "priority": "Priority of the assignment when a user gets the app through several groups.",
            "profile": "App-specific profile attributes applied to members of the group.",
            "lastUpdated": "Time at which the assignment was last updated.",
        },
    },
    "user_factors": {
        "description": "MFA factors enrolled by each Okta user. Only factors in the user's highest-priority authenticator enrollment policy are listed.",
        "docs_url": "https://developer.okta.com/docs/api/openapi/okta-management/management/tag/UserFactor/#tag/UserFactor/operation/listFactors",
        "columns": {
            "user_id": "Identifier of the user who enrolled the factor.",
            "id": "Unique identifier of the factor.",
            "factorType": "Type of the factor (e.g. push, token:software:totp, sms, webauthn).",
            "provider": "Provider of the factor (e.g. OKTA, GOOGLE, RSA).",
            "vendorName": "Name of the factor vendor.",
            "status": "Status of the factor (e.g. ACTIVE, PENDING_ACTIVATION, NOT_SETUP).",
            "profile": "Factor-specific attributes, such as the phone number or device name.",
            "created": "Time at which the factor was enrolled.",
            "lastUpdated": "Time at which the factor was last updated.",
        },
    },
}
