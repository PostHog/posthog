from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "devices": {
        "description": "A device is a container that collects data from a physical asset (sensor, machine, gateway) into variables.",
        "docs_url": "https://docs.ubidots.com/reference/device-object",
        "columns": {
            "id": "Unique identifier of the device.",
            "label": "Unique, URL-safe identifier used to reference the device in API calls.",
            "name": "Human-readable name of the device.",
            "description": "Free-text description of the device.",
            "organization": "Organization the device belongs to, if any.",
            "tags": "List of tags assigned to the device.",
            "properties": "Custom key-value properties attached to the device.",
            "isActive": "Whether the device is active.",
            "lastActivity": "When the device last received data.",
            "createdAt": "When the device was created.",
        },
    },
    "variables": {
        "description": "A variable holds one time series of dots (values) inside a device, e.g. temperature or humidity.",
        "docs_url": "https://docs.ubidots.com/reference/variable-object",
        "columns": {
            "id": "Unique identifier of the variable.",
            "label": "Unique, URL-safe identifier of the variable within its device.",
            "name": "Human-readable name of the variable.",
            "description": "Free-text description of the variable.",
            "device": "The device this variable belongs to.",
            "type": "Variable type: raw (ingested data) or synthetic (computed expression).",
            "unit": "Display unit of the variable's values.",
            "syntheticExpression": "Expression that computes the values of a synthetic variable.",
            "tags": "List of tags assigned to the variable.",
            "properties": "Custom key-value properties attached to the variable.",
            "lastValue": "The most recent dot received by the variable.",
            "lastActivity": "When the variable last received data.",
            "createdAt": "When the variable was created.",
        },
    },
    "device_groups": {
        "description": "A device group is a user-defined collection of devices, used to organize fleets and target events.",
        "docs_url": "https://docs.ubidots.com/reference/device-groups",
        "columns": {
            "id": "Unique identifier of the device group.",
            "label": "Unique, URL-safe identifier of the device group.",
            "name": "Human-readable name of the device group.",
            "devices": "Devices that belong to the group.",
            "createdAt": "When the device group was created.",
        },
    },
    "device_types": {
        "description": "A device type is a template of properties, variables, and appearance applied to devices of the same kind.",
        "docs_url": "https://docs.ubidots.com/reference/device-types",
        "columns": {
            "id": "Unique identifier of the device type.",
            "label": "Unique, URL-safe identifier of the device type.",
            "name": "Human-readable name of the device type.",
            "description": "Free-text description of the device type.",
            "properties": "Property definitions applied to devices of this type.",
            "variables": "Variable definitions applied to devices of this type.",
            "createdAt": "When the device type was created.",
        },
    },
    "events": {
        "description": "An event is a condition-based rule that triggers actions (email, SMS, webhook) when device data meets its criteria.",
        "docs_url": "https://docs.ubidots.com/reference/events",
        "columns": {
            "id": "Unique identifier of the event.",
            "name": "Human-readable name of the event.",
            "description": "Free-text description of the event.",
            "isActive": "Whether the event is enabled.",
            "createdAt": "When the event was created.",
        },
    },
    "values": {
        "description": "A dot: one timestamped data point of a variable's time series. Joins to the variables table via the variable column.",
        "docs_url": "https://docs.ubidots.com/v1.6/reference/get-variable-data-1",
        "columns": {
            "variable": "Identifier of the variable this dot belongs to (joins to variables.id).",
            "timestamp": "Unix epoch milliseconds at which the dot was recorded.",
            "value": "Numeric value of the dot.",
            "context": "Optional key-value metadata sent with the dot (e.g. GPS coordinates).",
            "created_at": "Unix epoch milliseconds at which the dot was ingested by Ubidots.",
        },
    },
}
