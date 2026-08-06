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
}
