from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

DEFAULT_PAGE_SIZE = 1000  # v4 max per_page


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
    page_size: int = DEFAULT_PAGE_SIZE
    # Set where the endpoint is only reachable per parent record, so rows are collected by
    # walking the parent listing first.
    fanout: Optional[DependentEndpointConfig] = None
    # "desc" holds the incremental watermark until the sync completes. Fan-out rows arrive
    # grouped by parent rather than in global time order, so a per-batch checkpoint would
    # advance the watermark past parents a crashed run has not reached yet.
    sort_mode: SortMode = "asc"

    @property
    def default_incremental_field(self) -> Optional[str]:
        return self.incremental_fields[0]["field"] if self.incremental_fields else None


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
    "broadcast_stats": ConvertKitEndpointConfig(
        name="broadcast_stats",
        path="/v4/broadcasts/stats",
        data_key="broadcasts",
        # Opens and clicks keep accumulating after a broadcast is sent, so the sent_after
        # window would freeze the numbers of every broadcast already synced.
    ),
    "form_subscribers": ConvertKitEndpointConfig(
        name="form_subscribers",
        path="/v4/forms/{form_id}/subscribers",
        data_key="subscribers",
        # A subscriber id is unique per account but repeats across forms.
        primary_keys=["form_id", "id"],
        # added_at is the row's own timestamp, but a subscriber removed and re-added to a form
        # gets a new one, so partition on the subscriber's immutable creation date instead.
        partition_key="created_at",
        supports_incremental=True,
        incremental_fields=[_datetime_field("added_at")],
        incremental_param_map={"added_at": "added_after"},
        extra_params={"status": "all"},
        sort_mode="desc",
        fanout=DependentEndpointConfig(
            parent_name="forms",
            resolve_param="form_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "form_id"},
            parent_params={"status": "all"},
        ),
    ),
    "tag_subscribers": ConvertKitEndpointConfig(
        name="tag_subscribers",
        path="/v4/tags/{tag_id}/subscribers",
        data_key="subscribers",
        primary_keys=["tag_id", "id"],
        partition_key="created_at",
        supports_incremental=True,
        incremental_fields=[_datetime_field("tagged_at")],
        incremental_param_map={"tagged_at": "tagged_after"},
        extra_params={"status": "all"},
        sort_mode="desc",
        fanout=DependentEndpointConfig(
            parent_name="tags",
            resolve_param="tag_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "tag_id"},
        ),
    ),
    "sequence_subscribers": ConvertKitEndpointConfig(
        name="sequence_subscribers",
        path="/v4/sequences/{sequence_id}/subscribers",
        data_key="subscribers",
        primary_keys=["sequence_id", "id"],
        partition_key="created_at",
        supports_incremental=True,
        incremental_fields=[_datetime_field("added_at")],
        incremental_param_map={"added_at": "added_after"},
        extra_params={"status": "all"},
        sort_mode="desc",
        fanout=DependentEndpointConfig(
            parent_name="sequences",
            resolve_param="sequence_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "sequence_id"},
        ),
    ),
}

ENDPOINTS = tuple(CONVERTKIT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CONVERTKIT_ENDPOINTS.items()
}
