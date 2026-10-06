from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "networks": {
        "description": "Networks that the API key can access in the selected Meraki organization.",
        "docs_url": "https://developer.cisco.com/meraki/api-v1/get-organization-networks/",
        "columns": {
            "id": "Identifier of the network.",
            "organizationId": "Identifier of the organization that contains the network.",
            "name": "Name of the network.",
            "productTypes": "Product types supported by the network.",
            "timeZone": "Time zone used by the network.",
            "tags": "Tags assigned to the network.",
        },
    },
    "devices": {
        "description": "Devices assigned to networks in the selected Meraki organization.",
        "docs_url": "https://developer.cisco.com/meraki/api-v1/get-organization-devices/",
        "columns": {
            "serial": "Serial number that identifies the device.",
            "networkId": "Identifier of the network that contains the device.",
            "name": "Name assigned to the device.",
            "model": "Device model.",
            "firmware": "Firmware version installed on the device.",
            "productType": "Product type of the device.",
        },
    },
    "inventory_devices": {
        "description": "Device inventory for the selected Meraki organization, including devices without an assigned network.",
        "docs_url": "https://developer.cisco.com/meraki/api-v1/get-organization-inventory-devices/",
        "columns": {
            "serial": "Serial number that identifies the device.",
            "networkId": "Identifier of the assigned network, if applicable.",
            "model": "Device model.",
            "claimedAt": "Time when the organization claimed the device.",
            "licenseExpirationDate": "Date when the device license expires.",
            "eox": "Dates and status for the end of device sales and support.",
        },
    },
    "uplink_statuses": {
        "description": "Current uplink status for MX, MG, and Z series devices in the selected Meraki organization.",
        "docs_url": "https://developer.cisco.com/meraki/api-v1/get-organization-uplinks-statuses/",
        "columns": {
            "serial": "Serial number that identifies the device.",
            "networkId": "Identifier of the network that contains the device.",
            "lastReportedAt": "Time when the device last reported its status.",
            "uplinks": "Uplink interfaces with their status and connection settings.",
            "highAvailability": "High availability settings and device role.",
        },
    },
    "assurance_alerts": {
        "description": "Active health alerts for the selected Meraki organization. Resolved and dismissed alerts are excluded.",
        "docs_url": "https://developer.cisco.com/meraki/api-v1/get-organization-assurance-alerts/",
        "columns": {
            "id": "Identifier of the health alert.",
            "startedAt": "Time when the alert started.",
            "resolvedAt": "Time when the alert was resolved, if applicable.",
            "dismissedAt": "Time when the alert was dismissed, if applicable.",
            "severity": "Severity of the alert.",
            "network": "Network where the alert occurred.",
            "scope": "Devices, applications, peers, and other items affected by the alert.",
        },
    },
}
