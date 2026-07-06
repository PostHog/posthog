from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class BrevoEndpointConfig:
    name: str
    path: str
    # Key wrapping the array in the JSON response, e.g. {"contacts": [...], "count": N}.
    data_key: str
    incremental_fields: list[IncrementalField]
    # Stable creation field used for datetime partitioning. Never use a "modified" field here.
    partition_key: Optional[str] = None
    page_size: int = 100
    # A few endpoints (e.g. /senders) return the full list in one shot with no limit/offset.
    paginate: bool = True
    # Maps a user-selected incremental field to the server-side query param that filters on it.
    incremental_param_map: dict[str, str] = field(default_factory=dict)


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Brevo (v3) endpoint catalog. Only `contacts` exposes genuine server-side timestamp filters
# (`createdSince` / `modifiedSince`); every other list endpoint sorts by creation date but offers
# no incremental filter, so those ship as full refresh.
BREVO_ENDPOINTS: dict[str, BrevoEndpointConfig] = {
    "contacts": BrevoEndpointConfig(
        name="contacts",
        path="/contacts",
        data_key="contacts",
        page_size=1000,  # max allowed by the API
        partition_key="createdAt",
        incremental_fields=[_datetime_field("createdAt"), _datetime_field("modifiedAt")],
        incremental_param_map={"createdAt": "createdSince", "modifiedAt": "modifiedSince"},
    ),
    "contact_lists": BrevoEndpointConfig(
        name="contact_lists",
        path="/contacts/lists",
        data_key="lists",
        page_size=50,  # max for the contacts list endpoints
        incremental_fields=[],
    ),
    "contact_folders": BrevoEndpointConfig(
        name="contact_folders",
        path="/contacts/folders",
        data_key="folders",
        page_size=50,
        incremental_fields=[],
    ),
    "contact_segments": BrevoEndpointConfig(
        name="contact_segments",
        path="/contacts/segments",
        data_key="segments",
        page_size=50,
        incremental_fields=[],
    ),
    "email_campaigns": BrevoEndpointConfig(
        name="email_campaigns",
        path="/emailCampaigns",
        data_key="campaigns",
        page_size=100,
        partition_key="createdAt",
        incremental_fields=[],
    ),
    "sms_campaigns": BrevoEndpointConfig(
        name="sms_campaigns",
        path="/smsCampaigns",
        data_key="campaigns",
        page_size=100,
        partition_key="createdAt",
        incremental_fields=[],
    ),
    "email_templates": BrevoEndpointConfig(
        name="email_templates",
        path="/smtp/templates",
        data_key="templates",
        page_size=100,
        incremental_fields=[],
    ),
    "senders": BrevoEndpointConfig(
        name="senders",
        path="/senders",
        data_key="senders",
        paginate=False,
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(BREVO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BREVO_ENDPOINTS.items() if config.incremental_fields
}
