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
    "device_parameters": {
        "description": "Status of each compliance parameter (security and configuration check) on each device.",
        "docs_url": "https://api-docs.kandji.io/",
        "columns": {
            "device_id": "Identifier of the device the parameter was evaluated on.",
            "item_id": "Identifier of the parameter.",
            "name": "Name of the parameter.",
            "category": "Category the parameter belongs to.",
            "subcategory": "Subcategory the parameter belongs to.",
            "status": "Result of the parameter on the device (PASS, ERROR, INCOMPATIBLE, PENDING, REMEDIATED, or WARNING).",
        },
    },
    "library_custom_apps": {
        "description": "Custom app library items (uploaded packages) defined in your tenant.",
        "docs_url": "https://api-docs.kandji.io/",
        "columns": {
            "id": "Unique identifier of the library item.",
            "name": "Name of the custom app.",
            "install_type": "How the app is installed (e.g. package, zip, image).",
            "install_enforcement": "Install enforcement mode (e.g. install_once, continuously_enforce, no_enforcement).",
            "active": "Whether the library item is active.",
            "show_in_self_service": "Whether the app is offered in Self Service.",
            "created_at": "Timestamp the library item was created.",
            "updated_at": "Timestamp the library item was last updated.",
        },
    },
    "library_custom_profiles": {
        "description": "Custom configuration profile library items defined in your tenant.",
        "docs_url": "https://api-docs.kandji.io/",
        "columns": {
            "id": "Unique identifier of the library item.",
            "name": "Name of the custom profile.",
            "active": "Whether the library item is active.",
            "profile": "The configuration profile payload (XML).",
            "mdm_identifier": "MDM payload identifier of the profile.",
            "created_at": "Timestamp the library item was created.",
            "updated_at": "Timestamp the library item was last updated.",
        },
    },
    "library_custom_scripts": {
        "description": "Custom script library items defined in your tenant.",
        "docs_url": "https://api-docs.kandji.io/",
        "columns": {
            "id": "Unique identifier of the library item.",
            "name": "Name of the custom script.",
            "active": "Whether the library item is active.",
            "execution_frequency": "How often the script runs (e.g. once, every_15_min, every_day, no_enforcement).",
            "script": "Body of the audit/enforcement script.",
            "remediation_script": "Body of the remediation script.",
            "created_at": "Timestamp the library item was created.",
            "updated_at": "Timestamp the library item was last updated.",
        },
    },
    "library_in_house_apps": {
        "description": "In-house (.ipa) app library items defined in your tenant.",
        "docs_url": "https://api-docs.kandji.io/",
        "columns": {
            "id": "Unique identifier of the library item.",
            "name": "Name of the in-house app library item.",
            "app_identifier": "Bundle identifier of the app.",
            "app_version": "Version of the uploaded app.",
            "minimum_os_version": "Minimum OS version the app supports.",
            "active": "Whether the library item is active.",
            "created_at": "Timestamp the library item was created.",
            "updated_at": "Timestamp the library item was last updated.",
        },
    },
    "users": {
        "description": "Users imported from your user directory integrations.",
        "docs_url": "https://api-docs.kandji.io/",
        "columns": {
            "id": "Unique identifier of the user.",
            "name": "Name of the user.",
            "email": "Email address of the user.",
            "active": "Whether the user is active in the directory.",
            "archived": "Whether the user is archived in Kandji.",
            "integration": "Directory integration the user was imported from.",
            "device_count": "Number of devices assigned to the user.",
            "created_at": "Timestamp the user was created in Kandji.",
            "updated_at": "Timestamp the user was last updated in Kandji.",
        },
    },
}
