from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "alerts": {
        "description": "Security risks that Microsoft Defender for Cloud Apps detects in connected cloud apps.",
        "docs_url": "https://learn.microsoft.com/en-us/defender-cloud-apps/api-alerts",
        "columns": {
            "_id": "The alert identifier.",
            "timestamp": "The time Microsoft Defender raised the alert, in milliseconds since the Unix epoch.",
            "title": "The alert title.",
            "description": "Details about the risk that triggered the alert.",
            "entities": "The accounts, devices, services, and other entities associated with the alert.",
            "severityValue": "The severity: 0 for low, 1 for medium, 2 for high, or 3 for informational.",
            "resolutionStatusValue": "The alert resolution status, including open, dismissed, resolved, false positive, benign, or true positive.",
        },
    },
    "files": {
        "description": "Metadata about files and folders in connected cloud apps, including ownership and modification dates.",
        "docs_url": "https://learn.microsoft.com/en-us/defender-cloud-apps/api-files",
        "columns": {},
    },
    "entities": {
        "description": "Users and accounts that use the organization's connected cloud apps.",
        "docs_url": "https://learn.microsoft.com/en-us/defender-cloud-apps/api-entities",
        "columns": {},
    },
}
