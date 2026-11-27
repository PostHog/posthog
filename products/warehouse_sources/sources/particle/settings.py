from dataclasses import dataclass, field

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType

PARTICLE_BASE_URL = "https://api.particle.io"

PAGE_SIZE = 100

DEVICES_SCHEMA_NAME = "devices"
EVENTS_SCHEMA_NAME = "events"
SIMS_SCHEMA_NAME = "sims"
SIM_DATA_USAGE_SCHEMA_NAME = "sim_data_usage"
DEVICE_DIAGNOSTICS_SCHEMA_NAME = "device_diagnostics"
DEVICE_GROUPS_SCHEMA_NAME = "device_groups"

# `{base}` is `/v1` for the token user's own (sandbox) resources and `/v1/products/<id>` for a
# product fleet. Particle serves the same resource under both roots.
SANDBOX_BASE_PATH = "/v1"
PRODUCT_BASE_PATH = "/v1/products/{product_id}"


@dataclass(frozen=True)
class ParticleEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    data_selector: str | None = None
    # `/v1/devices` answers with a bare list, where every other list wraps its rows.
    sandbox_body_is_list: bool = False
    # Product list endpoints page with `page`/`perPage` and `meta.total_pages`; the sandbox
    # variants return the whole collection in one response.
    paginated_in_product: bool = False
    product_only: bool = False
    fanout: DependentEndpointConfig | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    # Read by the fan-out helper's protocol only; the page size goes out as `perPage`.
    page_size: int = PAGE_SIZE


PULL_ENDPOINTS: dict[str, ParticleEndpointConfig] = {
    DEVICES_SCHEMA_NAME: ParticleEndpointConfig(
        name=DEVICES_SCHEMA_NAME,
        path="{base}/devices",
        primary_keys=["id"],
        data_selector="devices",
        sandbox_body_is_list=True,
        paginated_in_product=True,
    ),
    SIMS_SCHEMA_NAME: ParticleEndpointConfig(
        name=SIMS_SCHEMA_NAME,
        path="{base}/sims",
        # `_id` is the SIM's ICCID.
        primary_keys=["_id"],
        data_selector="sims",
        paginated_in_product=True,
    ),
    SIM_DATA_USAGE_SCHEMA_NAME: ParticleEndpointConfig(
        name=SIM_DATA_USAGE_SCHEMA_NAME,
        path="{base}/sims/{iccid}/data_usage",
        primary_keys=["iccid", "date"],
        data_selector="usage_by_day",
        fanout=DependentEndpointConfig(
            parent_name=SIMS_SCHEMA_NAME,
            resolve_param="iccid",
            resolve_field="_id",
            include_from_parent=["_id"],
            parent_field_renames={"_id": "iccid"},
            # A SIM released between the listing and this read has no usage to return.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
        # Particle only returns the current billing period and has no date filter. Merging on
        # `(iccid, date)` keeps earlier periods that a full refresh would delete.
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        default_incremental_field="date",
    ),
    DEVICE_DIAGNOSTICS_SCHEMA_NAME: ParticleEndpointConfig(
        name=DEVICE_DIAGNOSTICS_SCHEMA_NAME,
        path="{base}/diagnostics/{device_id}/last",
        primary_keys=["deviceID"],
        data_selector="diagnostics",
        fanout=DependentEndpointConfig(
            parent_name=DEVICES_SCHEMA_NAME,
            resolve_param="device_id",
            resolve_field="id",
            include_from_parent=[],
            # A device that never sent vitals, or was removed after the listing, has none to return.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    DEVICE_GROUPS_SCHEMA_NAME: ParticleEndpointConfig(
        name=DEVICE_GROUPS_SCHEMA_NAME,
        path="{base}/groups",
        primary_keys=["name"],
        data_selector="groups",
        product_only=True,
    ),
}

ENDPOINTS = (
    DEVICES_SCHEMA_NAME,
    EVENTS_SCHEMA_NAME,
    SIMS_SCHEMA_NAME,
    SIM_DATA_USAGE_SCHEMA_NAME,
    DEVICE_DIAGNOSTICS_SCHEMA_NAME,
    DEVICE_GROUPS_SCHEMA_NAME,
)

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
