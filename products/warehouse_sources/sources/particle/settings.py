PARTICLE_BASE_URL = "https://api.particle.io"

DEVICES_PAGE_SIZE = 100

DEVICES_SCHEMA_NAME = "devices"
EVENTS_SCHEMA_NAME = "events"

ENDPOINTS = (DEVICES_SCHEMA_NAME, EVENTS_SCHEMA_NAME)

# Particle keeps no event history to page through, so `events` only fills from webhook deliveries.
WEBHOOK_SCHEMA_NAMES = frozenset({EVENTS_SCHEMA_NAME})

WEBHOOK_RESOURCE_MAP = {EVENTS_SCHEMA_NAME: EVENTS_SCHEMA_NAME}

# Particle doesn't sign webhook deliveries, so `create_webhook` pins a generated secret in this
# header on every hook it creates, and the webhook template rejects a delivery without it.
WEBHOOK_SECRET_HEADER = "x-posthog-webhook-secret"

# Particle's documented template variables, sent as query parameters so Particle URL-encodes each
# value. The event data goes in the body instead: `{{{PARTICLE_EVENT_JSON}}}` is Particle's own
# serialization of the event, so data containing quotes or newlines stays valid JSON. Product
# variables render empty for devices outside a product.
WEBHOOK_QUERY = {
    "event": "{{{PARTICLE_EVENT_NAME}}}",
    "device_id": "{{{PARTICLE_DEVICE_ID}}}",
    "published_at": "{{{PARTICLE_PUBLISHED_AT}}}",
    "event_id": "{{{PARTICLE_EVENT_ID}}}",
    "product_id": "{{{PRODUCT_ID}}}",
    "firmware_version": "{{{PRODUCT_VERSION}}}",
}
WEBHOOK_BODY = "{{{PARTICLE_EVENT_JSON}}}"
