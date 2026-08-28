from dataclasses import dataclass
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

APITALLY_BASE_URL = "https://api.apitally.io"

# All non-Apps endpoints hang off a per-app path (/v1/apps/{app_id}/...); Apps is the
# parent list every other resource fans out from.
APP_ID_FANOUT = DependentEndpointConfig(
    parent_name="Apps",
    resolve_param="app_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "app_id"},
)


@dataclass
class ApitallyEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: str | None = None
    partition_key: str | None = None
    page_size: int = 100
    # None for endpoints the API returns as a single unpaginated collection (Apps, Endpoints) —
    # sending a limit/next_token param they don't document isn't worth the risk of a strict validator.
    page_size_param: str | None = "limit"
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_key: str | list[str] = "id"
    fanout: DependentEndpointConfig | None = None


APITALLY_ENDPOINTS: dict[str, ApitallyEndpointConfig] = {
    "Apps": ApitallyEndpointConfig(
        name="Apps",
        path="/v1/apps",
        incremental_fields=[],
        page_size_param=None,
        primary_key="id",
        partition_key="created_at",
    ),
    "Consumers": ApitallyEndpointConfig(
        name="Consumers",
        path="/v1/apps/{app_id}/consumers",
        incremental_fields=[],
        primary_key=["app_id", "id"],
        partition_key="created_at",
        # API orders consumers by id descending; only relevant to full-refresh page ordering here
        # since this endpoint has no incremental field.
        sort_mode="desc",
        fanout=APP_ID_FANOUT,
    ),
    "Endpoints": ApitallyEndpointConfig(
        name="Endpoints",
        path="/v1/apps/{app_id}/endpoints",
        incremental_fields=[],
        page_size_param=None,
        primary_key=["app_id", "id"],
        fanout=APP_ID_FANOUT,
    ),
    "Traffic": ApitallyEndpointConfig(
        name="Traffic",
        path="/v1/apps/{app_id}/traffic",
        incremental_fields=[incremental_field("period_end")],
        default_incremental_field="period_end",
        primary_key=["app_id", "period_start"],
        partition_key="period_start",
        fanout=APP_ID_FANOUT,
    ),
    "RequestLogs": ApitallyEndpointConfig(
        name="RequestLogs",
        path="/v1/apps/{app_id}/request-logs",
        incremental_fields=[incremental_field("timestamp")],
        default_incremental_field="timestamp",
        # request_uuid is documented as a globally unique request identifier, so it does not need
        # app_id in the key.
        primary_key="request_uuid",
        partition_key="timestamp",
        fanout=APP_ID_FANOUT,
    ),
}

ENDPOINTS = tuple(APITALLY_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APITALLY_ENDPOINTS.items()
}
