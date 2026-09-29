from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class FulcrumEndpointConfig:
    name: str
    path: str  # e.g. "/records.json"
    data_key: str  # response wrapper key holding the array (e.g. "records")
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None  # stable creation-time field for datetime partitioning
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Server-side `updated_since` time filter. Only records and audit_logs expose one;
    # everything else is full-refresh only.
    supports_incremental: bool = False
    # Order rows arrive in. Full-refresh endpoints checkpoint no watermark, so "asc" is a safe
    # default for them. "desc" makes the pipeline commit the watermark once at the end of the sync
    # instead of after every batch, which is what an endpoint with undocumented ordering needs.
    sort_mode: Literal["asc", "desc"] = "asc"
    # Extra static query params sent with every request to this endpoint.
    params: dict[str, Any] = field(default_factory=dict)
    # Set when the endpoint only exists under a parent resource and has to be fanned out.
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = 1000  # Fulcrum caps per_page at 20000; keep pages small to bound memory
    should_sync_default: bool = True

    @property
    def default_incremental_field(self) -> Optional[str]:
        # Also satisfies the fan-out helper's FanoutEndpointLike protocol.
        return self.incremental_fields[0]["field"] if self.incremental_fields else None


def _datetime_field(name: str) -> list[IncrementalField]:
    return [
        {
            "label": name,
            "type": IncrementalFieldType.DateTime,
            "field": name,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


FULCRUM_ENDPOINTS: dict[str, FulcrumEndpointConfig] = {
    # Records are the primary, high-volume stream. The list endpoint defaults to ordering by
    # updated_at ascending and exposes a genuine server-side `updated_since` filter (epoch
    # seconds), so it syncs incrementally on updated_at. Partition on created_at (stable).
    "records": FulcrumEndpointConfig(
        name="records",
        path="/records.json",
        data_key="records",
        partition_key="created_at",
        incremental_fields=_datetime_field("updated_at"),
        supports_incremental=True,
    ),
    # The resources below have no documented server-side time filter, so they're full refresh.
    "forms": FulcrumEndpointConfig(
        name="forms",
        path="/forms.json",
        data_key="forms",
        partition_key="created_at",
    ),
    "choice_lists": FulcrumEndpointConfig(
        name="choice_lists",
        path="/choice_lists.json",
        data_key="choice_lists",
        partition_key="created_at",
    ),
    "classification_sets": FulcrumEndpointConfig(
        name="classification_sets",
        path="/classification_sets.json",
        data_key="classification_sets",
        partition_key="created_at",
    ),
    "projects": FulcrumEndpointConfig(
        name="projects",
        path="/projects.json",
        data_key="projects",
        partition_key="created_at",
    ),
    "memberships": FulcrumEndpointConfig(
        name="memberships",
        path="/memberships.json",
        data_key="memberships",
        partition_key="created_at",
    ),
    "roles": FulcrumEndpointConfig(
        name="roles",
        path="/roles.json",
        data_key="roles",
    ),
    "changesets": FulcrumEndpointConfig(
        name="changesets",
        path="/changesets.json",
        data_key="changesets",
        partition_key="created_at",
    ),
    "webhooks": FulcrumEndpointConfig(
        name="webhooks",
        path="/webhooks.json",
        data_key="webhooks",
        partition_key="created_at",
    ),
    # Every version of every record. The history endpoint documents only `changeset_id` and
    # `deleted_form_id` filters — no time filter — so it is full refresh. Each row is one history
    # entry, identified by `history_id` and stamped with `history_created_at`.
    "records_history": FulcrumEndpointConfig(
        name="records_history",
        path="/records/history.json",
        data_key="records",
        primary_keys=["history_id"],
        partition_key="history_created_at",
    ),
    # Account-wide activity trail. `updated_since` is a genuine server-side filter (epoch seconds)
    # keyed off the entry's `time`, but the endpoint documents no ordering, so sort descending:
    # the watermark is then committed once the sync finishes rather than after each batch, which
    # is correct whichever order rows actually arrive in.
    "audit_logs": FulcrumEndpointConfig(
        name="audit_logs",
        path="/audit_logs.json",
        data_key="audit_logs",
        partition_key="time",
        incremental_fields=_datetime_field("time"),
        supports_incremental=True,
        sort_mode="desc",
    ),
    # Lookup resolving the group ids carried on memberships and projects. `associations=true` adds
    # the member/layer/project/form id arrays, so the group's contents come back on the same row.
    # Group objects carry no timestamps, so there is nothing stable to partition on.
    "groups": FulcrumEndpointConfig(
        name="groups",
        path="/groups.json",
        data_key="groups",
        params={"associations": "true"},
    ),
    # Form schema versions, needed to read records collected under an earlier definition. There is
    # no account-wide history list, so fan out over the forms endpoint.
    "form_history": FulcrumEndpointConfig(
        name="form_history",
        path="/forms/{form_id}/history.json",
        data_key="forms",
        primary_keys=["form_id", "version"],
        fanout=DependentEndpointConfig(
            parent_name="forms",
            resolve_param="form_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "form_id"},
        ),
    ),
    # Media metadata list endpoints. The identifier is `access_key` (a UUID), not `id`.
    "photos": FulcrumEndpointConfig(
        name="photos",
        path="/photos.json",
        data_key="photos",
        primary_keys=["access_key"],
        partition_key="created_at",
    ),
    "signatures": FulcrumEndpointConfig(
        name="signatures",
        path="/signatures.json",
        data_key="signatures",
        primary_keys=["access_key"],
        partition_key="created_at",
    ),
    "videos": FulcrumEndpointConfig(
        name="videos",
        path="/videos.json",
        data_key="videos",
        primary_keys=["access_key"],
        partition_key="created_at",
    ),
    "audio": FulcrumEndpointConfig(
        name="audio",
        path="/audio.json",
        data_key="audio",  # note: singular wrapper key, not "audios"
        primary_keys=["access_key"],
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(FULCRUM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FULCRUM_ENDPOINTS.items()
}
