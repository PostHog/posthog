"""Canonical, documentation-sourced descriptions for Google Tag Manager endpoints.

Sourced from the GTM API v2 resource representations
(https://developers.google.com/tag-platform/tag-manager/api/v2). Keyed by the endpoint names in
`settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced table. Columns are
the synced column names, which the pipeline converts to snake_case. Columns absent here fall back
to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

# Identity fields shared by every GTM resource.
_PATH = {"path": "The resource's API relative path, unique across the whole table."}
_ACCOUNT_ID = {"account_id": "The GTM account ID."}
_CONTAINER_ID = {"container_id": "The GTM container ID."}
_WORKSPACE_ID = {"workspace_id": "The GTM workspace ID."}
_FINGERPRINT = {"fingerprint": "Fingerprint computed at storage time, recomputed whenever the resource is modified."}
_TAG_MANAGER_URL = {"tag_manager_url": "Auto-generated link to this resource in the Tag Manager UI."}
_NOTES = {"notes": "User notes on how to apply this resource in the container."}
_PARENT_FOLDER_ID = {"parent_folder_id": "Parent folder ID."}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "accounts": {
        "description": "Google Tag Manager accounts the connected Google user can access.",
        "docs_url": "https://developers.google.com/tag-platform/tag-manager/api/v2/reference/accounts",
        "columns": {
            **_PATH,
            **_ACCOUNT_ID,
            "name": "Account display name.",
            "share_data": "Whether the account shares data anonymously with Google and others for benchmarking.",
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
            "public_id": "Container public ID (the GTM-XXXXXX ID used in the installed snippet).",
            "domain_name": "List of domain names associated with the container.",
            "usage_context": "Usage contexts for the container: web, android, ios, amp, or server.",
            "tag_ids": "All tag IDs that refer to this container.",
            "tagging_server_urls": "List of server-side container URLs for the container.",
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
            "tag_id": "The tag ID, unique within its workspace.",
            "name": "Tag display name.",
            "type": "GTM tag type, e.g. gaawe (GA4 event) or html (custom HTML).",
            "firing_trigger_id": "Trigger IDs that fire this tag when any of them is true and no blocking trigger matches.",
            "blocking_trigger_id": "Trigger IDs that prevent this tag from firing when any of them is true.",
            "parameter": "The tag's parameters.",
            "paused": "Whether the tag is paused, which prevents it from firing.",
            "live_only": "Whether the tag only fires in the live environment and not in preview or debug mode.",
            "tag_firing_option": "Option controlling how often the tag fires per event or page.",
            "priority": "User-defined numeric priority; tags fire asynchronously in priority order, higher values first.",
            "schedule_start_ms": "Start timestamp in milliseconds for scheduling the tag.",
            "schedule_end_ms": "End timestamp in milliseconds for scheduling the tag.",
            "setup_tag": "Setup tags that must fire before this tag.",
            "teardown_tag": "Teardown tags that fire after this tag.",
            "monitoring_metadata": "Key-value metadata added to event data for tag monitoring.",
            "consent_settings": "Consent settings of the tag.",
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
            "trigger_id": "The trigger ID, unique within its workspace.",
            "name": "Trigger display name.",
            "type": "The data layer event type that causes this trigger to fire, e.g. pageview, click, or customEvent.",
            "filter": "Conditions that must all be true for the trigger to fire.",
            "custom_event_filter": "Conditions evaluated for custom event triggers.",
            "auto_event_filter": "Conditions used for auto event tracking.",
            "event_name": "Name of the GTM event that is fired. Only valid for timer triggers.",
            "wait_for_tags": "Whether to delay form submits or link opens until all tags have fired.",
            "check_validation": "Whether to fire tags only when the submit or click event is not cancelled by another handler.",
            "unique_trigger_id": "Globally unique ID of the auto-generating listener backing this trigger.",
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
            "variable_id": "The variable ID, unique within its workspace.",
            "name": "Variable display name.",
            "type": "GTM variable type, e.g. jsm (custom JavaScript) or c (constant).",
            "parameter": "The variable's parameters.",
            "enabling_trigger_id": "Trigger IDs that enable this variable. Only valid for mobile containers.",
            "disabling_trigger_id": "Trigger IDs that disable this variable. Only valid for mobile containers.",
            "format_value": "Options for converting the variable's value, e.g. defaults for undefined or null values.",
            "schedule_start_ms": "Start timestamp in milliseconds for scheduling the variable.",
            "schedule_end_ms": "End timestamp in milliseconds for scheduling the variable.",
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
            "container_version_id": "The container version ID, unique within its container.",
            "name": "Container version display name.",
            "deleted": "Whether this container version has been deleted (archived).",
            "num_tags": "Number of tags in the container version.",
            "num_triggers": "Number of triggers in the container version.",
            "num_variables": "Number of variables in the container version.",
            "num_zones": "Number of zones in the container version.",
            "num_custom_templates": "Number of custom templates in the container version.",
            "num_clients": "Number of clients in the container version.",
            "num_gtag_configs": "Number of Google tag configs in the container version.",
            "num_transformations": "Number of transformations in the container version.",
        },
    },
}
