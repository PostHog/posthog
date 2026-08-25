from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from Kandji's (Iru) public API docs. Columns not covered here fall back to LLM enrichment,
# so partial coverage is fine; keys match the endpoint/schema names returned by `get_schemas`.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "devices": {
        "description": "Every device enrolled in your Kandji tenant, one row per device.",
        "docs_url": "https://api-docs.kandji.io/",
        "columns": {
            "device_id": "Unique identifier for the device in Kandji.",
            "device_name": "Display name of the device.",
            "serial_number": "Hardware serial number of the device.",
            "platform": "Device platform (e.g. Mac, iPhone, iPad, AppleTV).",
            "os_version": "Operating system version currently installed on the device.",
            "model": "Hardware model of the device.",
            "asset_tag": "Asset tag assigned to the device.",
            "blueprint_id": "Identifier of the blueprint the device is assigned to.",
            "blueprint_name": "Name of the blueprint the device is assigned to.",
            "last_check_in": "Timestamp of the device's most recent check-in with Kandji.",
            "user": "User associated with the device.",
        },
    },
    "blueprints": {
        "description": "Configuration blueprints defined in your tenant that group library items and settings.",
        "docs_url": "https://api-docs.kandji.io/",
        "columns": {
            "id": "Unique identifier for the blueprint.",
            "name": "Name of the blueprint.",
            "enrollment_code": "Enrollment code configuration for the blueprint.",
            "device_count": "Number of devices assigned to the blueprint.",
        },
    },
    "device_details": {
        "description": "Detailed inventory for each device (hardware, network, security, and OS sections).",
        "docs_url": "https://api-docs.kandji.io/",
        "columns": {
            "device_id": "Identifier of the device these details belong to.",
        },
    },
    "device_apps": {
        "description": "Applications installed on each device, one row per device/app pairing.",
        "docs_url": "https://api-docs.kandji.io/",
        "columns": {
            "device_id": "Identifier of the device the app is installed on.",
            "app_name": "Name of the installed application.",
            "version": "Installed version of the application.",
            "bundle_id": "Application bundle identifier.",
        },
    },
    "device_library_items": {
        "description": "Library items (profiles, apps, scripts) applied to each device and their status.",
        "docs_url": "https://api-docs.kandji.io/",
        "columns": {
            "device_id": "Identifier of the device the library item is applied to.",
            "id": "Unique identifier of the library item.",
            "name": "Name of the library item.",
            "status": "Installation/enforcement status of the library item on the device.",
        },
    },
}
