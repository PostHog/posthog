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
}
