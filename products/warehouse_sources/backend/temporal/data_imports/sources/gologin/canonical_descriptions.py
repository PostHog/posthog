from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "profiles": {
        "description": "Browser profiles that the user can access across workspaces.",
        "docs_url": "https://gologin.com/docs/api-reference/profile/get-all-profiles",
        "columns": {
            "id": "Unique identifier of the browser profile.",
            "name": "Name of the browser profile.",
            "createdAt": "Time when the profile was created.",
            "updatedAt": "Time when the profile was last updated.",
            "lastActivity": "Time of the last profile activity.",
            "folders": "Folders that contain the profile.",
            "tags": "Tags assigned to the profile.",
        },
    },
    "workspaces": {
        "description": "Workspaces that the user can access, with plan details and profile counts.",
        "docs_url": "https://gologin.com/docs/api-reference/workspace/get-all-workspaces",
        "columns": {
            "id": "Unique identifier of the workspace.",
            "name": "Name of the workspace.",
            "owner": "Owner of the workspace.",
            "memberCount": "Number of workspace members.",
            "profilesCount": "Number of profiles in the workspace.",
        },
    },
    "proxy_devices": {
        "description": "The user's proxy devices and their proxy and SMS status.",
        "docs_url": "https://api.gologin.com/docs#/Proxy%20Devices/ProxyDevicesController_getDevices",
        "columns": {
            "id": "Unique identifier of the proxy device.",
            "name": "Name of the proxy device.",
            "model": "Model of the proxy device.",
            "ip": "IP address of the proxy device.",
            "country": "Country code of the proxy device.",
            "proxyStatus": "Whether the proxy is active or inactive.",
            "smsStatus": "Whether SMS is active or inactive.",
            "createdAt": "Time when the device was created.",
            "updatedAt": "Time when the device was last updated.",
        },
    },
    "tags": {
        "description": "Tags and custom statuses that can be assigned to profiles, one row per workspace and tag.",
        "docs_url": "https://gologin.com/docs/api-reference/tags/get-all-tags",
        "columns": {
            "id": "Unique identifier of the tag.",
            "workspace_id": "Identifier of the workspace that contains the tag.",
            "title": "Name of the tag.",
            "color": "Display color of the tag.",
            "field": "Whether the entry is a tag (`tags`) or a custom status (`custom-status`).",
        },
    },
    "folders": {
        "description": "Profile folders in each workspace, with the current user's folder permissions.",
        "docs_url": "https://gologin.com/docs/api-reference/workspace/get-workspace-info",
        "columns": {
            "id": "Unique identifier of the folder.",
            "workspace_id": "Identifier of the workspace that contains the folder.",
            "name": "Name of the folder. Profiles reference folders by this name.",
            "permissions": "Actions the current user can take in the folder.",
            "order": "Position of the folder in the folder list.",
            "associatedProfiles": "Identifiers of the profiles in the folder.",
            "isAllProfiles": "Whether the folder is the workspace's all-profiles folder.",
        },
    },
    "deleted_profiles": {
        "description": "Profiles deleted from a workspace. GoLogin keeps a deleted profile for 120 hours.",
        "docs_url": "https://gologin.com/docs/api-reference/profile/get-list-of-deleted-profiles",
        "columns": {
            "profileId": "Identifier of the deleted profile.",
            "workspace_id": "Identifier of the workspace the profile was deleted from.",
            "name": "Name of the deleted profile.",
            "deletedAt": "Time when the profile was deleted.",
            "deletedByUserEmail": "Email of the user who deleted the profile.",
        },
    },
    "cloud_usage_daily": {
        "description": "Daily cloud browser usage per workspace.",
        "docs_url": "https://gologin.com/docs/api-reference/cloud-usage/get-detailed-cloud-usage-statistics-for-a-workspace",
        "columns": {
            "date": "Day the usage applies to.",
            "workspace_id": "Identifier of the workspace.",
            "launches": "Number of cloud profile launches on the day.",
            "hours": "Cloud browser hours used on the day.",
            "maxConcurrentInstances": "Highest number of cloud profiles running at the same time on the day.",
        },
    },
}
