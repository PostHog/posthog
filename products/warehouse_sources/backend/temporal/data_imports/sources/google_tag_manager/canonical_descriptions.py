"""Canonical, documentation-sourced descriptions for Google Tag Manager endpoints.

Sourced from the GTM API v2 resource representations
(https://developers.google.com/tag-platform/tag-manager/api/v2). Keyed by the endpoint names in
`settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced table. Columns are
the raw GTM API response field names. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Identity fields shared by every GTM resource.
_PATH = {"path": "The resource's API relative path, unique across the whole table."}
_ACCOUNT_ID = {"accountId": "The GTM account ID."}
_CONTAINER_ID = {"containerId": "The GTM container ID."}
_WORKSPACE_ID = {"workspaceId": "The GTM workspace ID."}
_FINGERPRINT = {"fingerprint": "Fingerprint computed at storage time, recomputed whenever the resource is modified."}
_TAG_MANAGER_URL = {"tagManagerUrl": "Auto-generated link to this resource in the Tag Manager UI."}
_NOTES = {"notes": "User notes on how to apply this resource in the container."}
_PARENT_FOLDER_ID = {"parentFolderId": "Parent folder ID."}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "accounts": {
        "description": "Google Tag Manager accounts the connected Google user can access.",
        "docs_url": "https://developers.google.com/tag-platform/tag-manager/api/v2/reference/accounts",
        "columns": {
            **_PATH,
            **_ACCOUNT_ID,
            "name": "Account display name.",
            "shareData": "Whether the account shares data anonymously with Google and others for benchmarking.",
            **_FINGERPRINT,
            **_TAG_MANAGER_URL,
            "features": "Read-only account feature set.",
        },
    },
    "containers": {
        "description": "Containers in each account. A container holds the tags, triggers, and variables for one site or app.",
        "docs_url": "https://developers.google.com/tag-platform/tag-manager/api/v2/reference/accounts/containers",
        "columns": {
            **_PATH,
            **_ACCOUNT_ID,
            **_CONTAINER_ID,
            "name": "Container display name.",
            "publicId": "Container public ID (the GTM-XXXXXX ID used in the installed snippet).",
            "domainName": "List of domain names associated with the container.",
            "usageContext": "Usage contexts for the container: web, android, ios, amp, or server.",
            "tagIds": "All tag IDs that refer to this container.",
            "taggingServerUrls": "List of server-side container URLs for the container.",
            **_NOTES,
            **_FINGERPRINT,
            **_TAG_MANAGER_URL,
            "features": "Read-only container feature set.",
        },
    },
    "workspaces": {
        "description": "Workspaces in each container. A workspace is a working copy of the container configuration where changes are drafted before publishing.",
        "docs_url": "https://developers.google.com/tag-platform/tag-manager/api/v2/reference/accounts/containers/workspaces",
        "columns": {
            **_PATH,
            **_ACCOUNT_ID,
            **_CONTAINER_ID,
            **_WORKSPACE_ID,
            "name": "Workspace display name.",
            "description": "Workspace description.",
            **_FINGERPRINT,
            **_TAG_MANAGER_URL,
        },
    },
    "tags": {
        "description": "Tags in each workspace. A tag is a snippet (analytics, marketing, or custom code) that fires when its triggers match.",
        "docs_url": "https://developers.google.com/tag-platform/tag-manager/api/v2/reference/accounts/containers/workspaces/tags",
        "columns": {
            **_PATH,
            **_ACCOUNT_ID,
            **_CONTAINER_ID,
            **_WORKSPACE_ID,
            "tagId": "The tag ID, unique within its workspace.",
            "name": "Tag display name.",
            "type": "GTM tag type, e.g. gaawe (GA4 event) or html (custom HTML).",
            "firingTriggerId": "Trigger IDs that fire this tag when any of them is true and no blocking trigger matches.",
            "blockingTriggerId": "Trigger IDs that prevent this tag from firing when any of them is true.",
            "parameter": "The tag's parameters.",
            "paused": "Whether the tag is paused, which prevents it from firing.",
            "liveOnly": "Whether the tag only fires in the live environment and not in preview or debug mode.",
            "tagFiringOption": "Option controlling how often the tag fires per event or page.",
            "priority": "User-defined numeric priority; tags fire asynchronously in priority order, higher values first.",
            "scheduleStartMs": "Start timestamp in milliseconds for scheduling the tag.",
            "scheduleEndMs": "End timestamp in milliseconds for scheduling the tag.",
            "setupTag": "Setup tags that must fire before this tag.",
            "teardownTag": "Teardown tags that fire after this tag.",
            "monitoringMetadata": "Key-value metadata added to event data for tag monitoring.",
            "consentSettings": "Consent settings of the tag.",
            **_NOTES,
            **_PARENT_FOLDER_ID,
            **_FINGERPRINT,
            **_TAG_MANAGER_URL,
        },
    },
    "triggers": {
        "description": "Triggers in each workspace. A trigger defines the conditions under which tags fire.",
        "docs_url": "https://developers.google.com/tag-platform/tag-manager/api/v2/reference/accounts/containers/workspaces/triggers",
        "columns": {
            **_PATH,
            **_ACCOUNT_ID,
            **_CONTAINER_ID,
            **_WORKSPACE_ID,
            "triggerId": "The trigger ID, unique within its workspace.",
            "name": "Trigger display name.",
            "type": "The data layer event type that causes this trigger to fire, e.g. pageview, click, or customEvent.",
            "filter": "Conditions that must all be true for the trigger to fire.",
            "customEventFilter": "Conditions evaluated for custom event triggers.",
            "autoEventFilter": "Conditions used for auto event tracking.",
            "eventName": "Name of the GTM event that is fired. Only valid for timer triggers.",
            "waitForTags": "Whether to delay form submits or link opens until all tags have fired.",
            "checkValidation": "Whether to fire tags only when the submit or click event is not cancelled by another handler.",
            "uniqueTriggerId": "Globally unique ID of the auto-generating listener backing this trigger.",
            "parameter": "Additional parameters.",
            **_NOTES,
            **_PARENT_FOLDER_ID,
            **_FINGERPRINT,
            **_TAG_MANAGER_URL,
        },
    },
    "variables": {
        "description": "Variables in each workspace. A variable is a named value (built-in or user-defined) that tags, triggers, and other variables can reference.",
        "docs_url": "https://developers.google.com/tag-platform/tag-manager/api/v2/reference/accounts/containers/workspaces/variables",
        "columns": {
            **_PATH,
            **_ACCOUNT_ID,
            **_CONTAINER_ID,
            **_WORKSPACE_ID,
            "variableId": "The variable ID, unique within its workspace.",
            "name": "Variable display name.",
            "type": "GTM variable type, e.g. jsm (custom JavaScript) or c (constant).",
            "parameter": "The variable's parameters.",
            "enablingTriggerId": "Trigger IDs that enable this variable. Only valid for mobile containers.",
            "disablingTriggerId": "Trigger IDs that disable this variable. Only valid for mobile containers.",
            "formatValue": "Options for converting the variable's value, e.g. defaults for undefined or null values.",
            "scheduleStartMs": "Start timestamp in milliseconds for scheduling the variable.",
            "scheduleEndMs": "End timestamp in milliseconds for scheduling the variable.",
            **_NOTES,
            **_PARENT_FOLDER_ID,
            **_FINGERPRINT,
            **_TAG_MANAGER_URL,
        },
    },
    "container_versions": {
        "description": "Version headers for each container: one row per saved container version, including deleted (archived) versions.",
        "docs_url": "https://developers.google.com/tag-platform/tag-manager/api/reference/rest/v2/ContainerVersionHeader",
        "columns": {
            **_PATH,
            **_ACCOUNT_ID,
            **_CONTAINER_ID,
            "containerVersionId": "The container version ID, unique within its container.",
            "name": "Container version display name.",
            "deleted": "Whether this container version has been deleted (archived).",
            "numTags": "Number of tags in the container version.",
            "numTriggers": "Number of triggers in the container version.",
            "numVariables": "Number of variables in the container version.",
            "numZones": "Number of zones in the container version.",
            "numCustomTemplates": "Number of custom templates in the container version.",
            "numClients": "Number of clients in the container version.",
            "numGtagConfigs": "Number of Google tag configs in the container version.",
            "numTransformations": "Number of transformations in the container version.",
        },
    },
}
