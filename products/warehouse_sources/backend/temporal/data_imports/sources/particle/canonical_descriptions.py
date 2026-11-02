from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "devices": {
        "description": "A Particle device: the user's own sandbox devices, or every device in the configured product.",
        "docs_url": "https://docs.particle.io/reference/cloud-apis/api/#list-devices",
        "columns": {
            "id": "Device ID.",
            "name": "Device name.",
            "online": "Whether the device is connected to the Particle cloud. Cellular devices can lag going offline.",
            "last_heard": "When the cloud last heard from the device.",
            "last_handshake_at": "When the device last completed a cloud handshake.",
            "product_id": "Product the device belongs to.",
            "platform_id": "Hardware platform of the device.",
            "cellular": "Whether the device is cellular.",
            "serial_number": "Serial number of the device.",
            "system_firmware_version": "Device OS version running on the device.",
            "firmware_version": "Product firmware version running on the device.",
            "groups": "Product device groups the device belongs to.",
            "quarantined": "Whether the device is quarantined in the product.",
            "development": "Whether the device is marked as a development device.",
        },
    },
    "events": {
        "description": "An event a device published with Particle.publish(), delivered to PostHog by a Particle webhook.",
        "docs_url": "https://docs.particle.io/reference/cloud-apis/webhooks/",
        "columns": {
            "event_id": "Unique ID Particle generated for the event.",
            "event": "Event name the device published.",
            "data": "Data published with the event, as a string. JSON payloads are kept as JSON text.",
            "device_id": "ID of the device that published the event.",
            "product_id": "Product of the device that published the event. Empty for sandbox devices.",
            "firmware_version": "Product firmware version that published the event. Empty for sandbox devices.",
            "published_at": "When the device published the event.",
        },
    },
}
