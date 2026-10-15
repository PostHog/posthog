from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "users": {
        "description": "User identities in the JumpCloud directory, including their account state and profile attributes.",
        "docs_url": "https://docs.jumpcloud.com/api/1.0/index.html#tag/Systemusers",
        "columns": {
            "_id": "Unique identifier of the user.",
            "email": "The user's email address.",
            "username": "The user's JumpCloud username.",
            "firstname": "The user's first name.",
            "lastname": "The user's last name.",
            "displayname": "The user's display name.",
            "activated": "Whether the user account has been activated.",
            "suspended": "Whether the user account is suspended.",
            "account_locked": "Whether the account is locked out (e.g. after failed login attempts).",
            "state": "Lifecycle state of the user (STAGED, ACTIVATED, or SUSPENDED).",
            "created": "Timestamp when the user was created in JumpCloud.",
            "department": "The user's department.",
            "employeeIdentifier": "Employee identifier for the user, unique within the organization.",
            "mfa": "The user's multi-factor authentication configuration and status.",
            "sudo": "Whether the user has administrator (sudo) permissions on bound systems.",
            "totp_enabled": "Whether time-based one-time password MFA is enabled for the user.",
        },
    },
    "systems": {
        "description": "Devices (workstations and servers) managed by the JumpCloud agent.",
        "docs_url": "https://docs.jumpcloud.com/api/1.0/index.html#tag/Systems",
        "columns": {
            "_id": "Unique identifier of the system.",
            "hostname": "Hostname reported by the device.",
            "displayName": "Display name of the system in the admin console.",
            "os": "Operating system family (e.g. Mac OS X, Windows, Ubuntu).",
            "version": "Operating system version.",
            "arch": "CPU architecture of the device.",
            "agentVersion": "Version of the JumpCloud agent installed on the device.",
            "active": "Whether the device is currently connected to JumpCloud.",
            "remoteIP": "Public IP address the device last connected from.",
            "lastContact": "Timestamp of the device's last check-in with JumpCloud.",
            "created": "Timestamp when the system was enrolled in JumpCloud.",
            "allowSshPasswordAuthentication": "Whether SSH password authentication is allowed on the device.",
            "allowMultiFactorAuthentication": "Whether multi-factor authentication is enabled on the device.",
        },
    },
    "user_groups": {
        "description": "User groups used to grant collections of users access to resources (apps, systems, networks).",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/User-Groups",
        "columns": {
            "id": "Unique identifier of the group.",
            "name": "Display name of the group.",
            "type": "Group type discriminator (user_group).",
            "description": "Description of the group.",
            "email": "Email address associated with the group, if any.",
            "memberQuery": "Dynamic membership query for the group, if membership is rule-based.",
            "membershipMethod": "How membership is managed (static or dynamic).",
        },
    },
    "system_groups": {
        "description": "Device groups used to apply policies and access to collections of systems.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Groups",
        "columns": {
            "id": "Unique identifier of the group.",
            "name": "Display name of the group.",
            "type": "Group type discriminator (system_group).",
            "description": "Description of the group.",
        },
    },
    "applications": {
        "description": "SSO applications configured in JumpCloud (SAML, OIDC, and bookmark apps).",
        "docs_url": "https://docs.jumpcloud.com/api/1.0/index.html#tag/Applications",
        "columns": {
            "_id": "Unique identifier of the application.",
            "name": "Internal name of the application connector.",
            "displayName": "Name of the application shown in the admin console.",
            "displayLabel": "Label shown to users in the JumpCloud user portal.",
            "ssoUrl": "IdP-initiated SSO URL for the application.",
            "sso": "SSO protocol configuration for the application.",
            "config": "Connector-specific configuration for the application.",
        },
    },
    "user_group_members": {
        "description": "Users that are members of each user group, one row per group and user.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/User-Group-Members-&-Membership/operation/graph_userGroupMembership",
        "columns": {
            "group_id": "Identifier of the user group (joins to user_groups.id).",
            "id": "Identifier of the member user (joins to users._id).",
            "type": "Graph object type of the member.",
            "compiledAttributes": "Graph attributes compiled across every path to the member.",
            "paths": "Each path through the JumpCloud graph that connects the member, as a list of edges.",
        },
    },
    "system_group_members": {
        "description": "Systems that are members of each system group, one row per group and system.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Group-Members-&-Membership/operation/graph_systemGroupMembership",
        "columns": {
            "group_id": "Identifier of the system group (joins to system_groups.id).",
            "id": "Identifier of the member system (joins to systems._id).",
            "type": "Graph object type of the member.",
            "compiledAttributes": "Graph attributes compiled across every path to the member.",
            "paths": "Each path through the JumpCloud graph that connects the member, as a list of edges.",
        },
    },
    "application_users": {
        "description": "Users bound to each SSO application, directly or through a user group.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/Applications/operation/graph_applicationTraverseUser",
        "columns": {
            "application_id": "Identifier of the application (joins to applications._id).",
            "id": "Identifier of the bound user (joins to users._id).",
            "type": "Graph object type of the member.",
            "compiledAttributes": "Graph attributes compiled across every path to the member.",
            "paths": "Each path through the JumpCloud graph that connects the member, as a list of edges.",
        },
    },
    "application_user_groups": {
        "description": "User groups bound to each SSO application.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/Applications/operation/graph_applicationTraverseUserGroup",
        "columns": {
            "application_id": "Identifier of the application (joins to applications._id).",
            "id": "Identifier of the bound user group (joins to user_groups.id).",
            "type": "Graph object type of the member.",
            "compiledAttributes": "Graph attributes compiled across every path to the member.",
            "paths": "Each path through the JumpCloud graph that connects the member, as a list of edges.",
        },
    },
    "system_users": {
        "description": "Users bound to each system, directly or through a user or system group, so they can log in to it.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/Systems/operation/graph_systemTraverseUser",
        "columns": {
            "system_id": "Identifier of the system (joins to systems._id).",
            "id": "Identifier of the bound user (joins to users._id).",
            "type": "Graph object type of the member.",
            "compiledAttributes": "Graph attributes compiled across every path to the member.",
            "paths": "Each path through the JumpCloud graph that connects the member, as a list of edges.",
        },
    },
    "policies": {
        "description": "Device policies configured in JumpCloud, each built from a policy template.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/Policies/operation/policies_list",
        "columns": {
            "id": "Unique identifier of the policy.",
            "name": "Name of the policy.",
            "template": "The policy template the policy is built from, including its OS family and activation type.",
        },
    },
    "policy_results": {
        "description": "Every recorded application of a policy to a device, with its outcome. Use it to follow compliance over time.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/Policies/operation/policyresults_org_list",
        "columns": {
            "id": "Unique identifier of the policy result.",
            "policyID": "Identifier of the applied policy (joins to policies.id).",
            "systemID": "Identifier of the device the policy was applied to (joins to systems._id).",
            "startedAt": "Time the policy application started.",
            "endedAt": "Time the policy application ended.",
            "success": "Whether the policy applied successfully.",
            "state": "State of the policy application.",
            "exitStatus": "Exit status of the policy application on the device.",
            "detail": "Details about the result.",
        },
    },
    "policy_statuses": {
        "description": "The latest result of each policy on each device it applies to: the current compliance state.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/Policies/operation/policystatuses_policiesList",
        "columns": {
            "policy_id": "Identifier of the policy (joins to policies.id).",
            "id": "Unique identifier of the latest policy result.",
            "systemID": "Identifier of the device (joins to systems._id).",
            "success": "Whether the latest application of the policy succeeded.",
            "startedAt": "Time the latest policy application started.",
            "endedAt": "Time the latest policy application ended.",
        },
    },
    "alerts": {
        "description": "Alerts raised by JumpCloud for device and identity health, with their status and severity.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/Alerts",
        "columns": {
            "objectId": "Unique identifier of the alert.",
            "title": "Title of the alert.",
            "description": "Description of the alert.",
            "category": "Category of the alert.",
            "severity": "Severity of the alert.",
            "status": "Status of the alert (e.g. open, acknowledged, resolved).",
            "sourceType": "Type of object the alert is about.",
            "sourceId": "Identifier of the object the alert is about.",
            "sourceName": "Name of the object the alert is about.",
            "occurrencesCount": "Number of times the alert has fired.",
            "firstOccurredAt": "Time the alert first fired.",
            "lastOccurredAt": "Time the alert last fired.",
            "acknowledgedAt": "Time the alert was acknowledged.",
            "resolvedAt": "Time the alert was resolved.",
            "createdAt": "Time the alert was created.",
            "updatedAt": "Time the alert was last updated.",
        },
    },
    "alert_occurrences": {
        "description": "Each time an alert fired, with the context of that occurrence.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/Alerts",
        "columns": {
            "alert_id": "Identifier of the alert (joins to alerts.objectId).",
            "alertObjectId": "Identifier of the alert the occurrence belongs to.",
            "occurredAt": "Time the occurrence happened.",
            "context": "Details of the occurrence.",
            "createdAt": "Time the occurrence was recorded.",
            "updatedAt": "Time the occurrence was last updated.",
        },
    },
    "identity_risk_events": {
        "description": "Risk-scored identity events detected by JumpCloud, such as risky logins, with their risk factors and resolution.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/Identity-Risk",
        "columns": {
            "objectId": "Unique identifier of the risk event.",
            "identityObjectId": "Identifier of the identity the risk event is about.",
            "identityIdentifier": "Identifier (e.g. email or username) of the identity.",
            "identityType": "Type of the identity.",
            "level": "Risk level of the event.",
            "score": "Risk score of the event.",
            "riskFactors": "Risk factors that contributed to the score.",
            "occurrenceCount": "Number of times the risk event occurred.",
            "firstOccurrenceAt": "Time the risk event first occurred.",
            "lastOccurrenceAt": "Time the risk event last occurred.",
            "resolutionStatus": "Whether the risk event is open or resolved.",
            "resolvedAt": "Time the risk event was resolved.",
            "clientIp": "IP address of the client involved in the event.",
            "countryCode": "Country of the client IP address.",
            "loginStatus": "Whether the login attempt succeeded.",
            "mfaStatus": "Whether multi-factor authentication succeeded.",
            "createdAt": "Time the risk event was created.",
        },
    },
    "system_insights_alf": {
        "description": "macOS application layer firewall settings per device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_apps": {
        "description": "Applications installed on macOS devices.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_battery": {
        "description": "Battery health and charge state of each device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_bitlocker_info": {
        "description": "BitLocker drive encryption status of Windows devices.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_browser_plugins": {
        "description": "Browser plugins installed on each device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_chrome_extensions": {
        "description": "Google Chrome extensions installed on each device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_disk_encryption": {
        "description": "Disk encryption status of each volume on each device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_disk_info": {
        "description": "Physical disks attached to each device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_firefox_addons": {
        "description": "Firefox add-ons installed on each device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_kernel_info": {
        "description": "Kernel version and boot details of each device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_linux_packages": {
        "description": "Packages installed on Linux devices.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
        },
    },
    "system_insights_logged_in_users": {
        "description": "Users logged in to each device when System Insights collected the data.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_os_version": {
        "description": "Operating system name and version of each device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_patches": {
        "description": "Windows updates (hotfixes) installed on each device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_programs": {
        "description": "Programs installed on Windows devices.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_safari_extensions": {
        "description": "Safari extensions installed on each device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_secureboot": {
        "description": "Secure Boot status of each device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_sip_config": {
        "description": "macOS System Integrity Protection configuration of each device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_system_info": {
        "description": "Hardware details of each device, such as CPU, memory, and serial number.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_uptime": {
        "description": "Time since each device last booted.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_usb_devices": {
        "description": "USB devices attached to each device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_users": {
        "description": "Local operating system accounts on each device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_windows_security_center": {
        "description": "Windows Security Center status (firewall, antivirus, updates) of each device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "system_insights_windows_security_products": {
        "description": "Security products (such as antivirus) registered with Windows on each device.",
        "docs_url": "https://docs.jumpcloud.com/api/2.0/index.html#tag/System-Insights",
        "columns": {
            "system_id": "Identifier of the device (joins to systems._id).",
            "collection_time": "Time System Insights collected the row.",
        },
    },
    "events": {
        "description": "Directory Insights activity events across JumpCloud services: admin console actions, directory changes, SSO, RADIUS, LDAP, MDM, and agent-reported system events.",
        "docs_url": "https://docs.jumpcloud.com/api/insights/directory/1.0/index.html",
        "columns": {
            "id": "Unique identifier of the event.",
            "timestamp": "Time the event occurred.",
            "service": "JumpCloud service that emitted the event (e.g. directory, sso, radius, ldap, systems).",
            "event_type": "Type of the event (e.g. login_attempt, user_created, admin_login_attempt).",
            "initiated_by": "Actor that initiated the event (user, admin, or system identity).",
            "client_ip": "IP address the action originated from.",
            "success": "Whether the attempted action succeeded.",
            "geoip": "GeoIP enrichment for the originating IP address.",
            "useragent": "Parsed user agent of the client that performed the action.",
            "organization": "Identifier of the JumpCloud organization the event belongs to.",
        },
    },
}
