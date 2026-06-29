from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ConvertKitEndpointConfig:
    name: str
    path: str
    # Top-level key wrapping the list in the JSON response (e.g. {"subscribers": [...]}).
    data_key: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable datetime field to partition by. Never use a field that mutates (e.g. updated_at).
    partition_key: Optional[str] = None
    supports_incremental: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Maps a selected incremental field name to the server-side filter query param it drives,
    # e.g. {"created_at": "created_after"}.
    incremental_param_map: dict[str, str] = field(default_factory=dict)
    # Static query params always sent to the endpoint (e.g. status=all to include every record).
    extra_params: dict[str, str] = field(default_factory=dict)


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


CONVERTKIT_ENDPOINTS: dict[str, ConvertKitEndpointConfig] = {
    # The only list endpoint with server-side timestamp filters (created_after / updated_after).
    "subscribers": ConvertKitEndpointConfig(
        name="subscribers",
        path="/v4/subscribers",
        data_key="subscribers",
        partition_key="created_at",
        supports_incremental=True,
        incremental_fields=[_datetime_field("created_at"), _datetime_field("updated_at")],
        incremental_param_map={"created_at": "created_after", "updated_at": "updated_after"},
        # Default status filter is "active"; "all" pulls every subscriber regardless of state.
        extra_params={"status": "all"},
    ),
    "broadcasts": ConvertKitEndpointConfig(
        name="broadcasts",
        path="/v4/broadcasts",
        data_key="broadcasts",
        partition_key="created_at",
    ),
    "forms": ConvertKitEndpointConfig(
        name="forms",
        path="/v4/forms",
        data_key="forms",
        partition_key="created_at",
        extra_params={"status": "all"},
    ),
    "sequences": ConvertKitEndpointConfig(
        name="sequences",
        path="/v4/sequences",
        data_key="sequences",
        partition_key="created_at",
    ),
    "tags": ConvertKitEndpointConfig(
        name="tags",
        path="/v4/tags",
        data_key="tags",
        partition_key="created_at",
    ),
    "custom_fields": ConvertKitEndpointConfig(
        name="custom_fields",
        path="/v4/custom_fields",
        data_key="custom_fields",
    ),
    "purchases": ConvertKitEndpointConfig(
        name="purchases",
        path="/v4/purchases",
        data_key="purchases",
        # Purchases have no created_at; transaction_time is the stable creation timestamp.
        partition_key="transaction_time",
    ),
    "email_templates": ConvertKitEndpointConfig(
        name="email_templates",
        path="/v4/email_templates",
        data_key="email_templates",
    ),
}

ENDPOINTS = tuple(CONVERTKIT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CONVERTKIT_ENDPOINTS.items()
}
