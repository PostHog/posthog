from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


CREATED_AT_INCREMENTAL = _datetime_field("created_at")
UPDATED_AT_INCREMENTAL = _datetime_field("updated_at")


@dataclass
class JotformEndpointConfig:
    name: str
    # Path relative to the regional API host. A `{form_id}` placeholder marks a per-form fan-out
    # endpoint (questions), which iterates every form on the account.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style field,
    # which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    partition_format: Optional[PartitionFormat] = None
    page_size: int = 100
    # Fan out one request per form. The questions response is an object keyed by question id (not a
    # list), so it uses the dedicated questions iterator rather than offset pagination.
    fan_out_over_forms: bool = False


# Forms and submissions expose Jotform's server-side `filter={"<field>:gt":"..."}` timestamp filter,
# so they're advertised as incremental. Reports has no documented timestamp filter (full refresh).
# Questions describe form structure (no timestamps), fan out per form, and are full refresh; their
# `qid` is unique only within a form, so the form id is part of the primary key.
JOTFORM_ENDPOINTS: dict[str, JotformEndpointConfig] = {
    "forms": JotformEndpointConfig(
        name="forms",
        path="/user/forms",
        primary_keys=["id"],
        partition_key="created_at",
        partition_format="month",
        default_incremental_field="created_at",
        incremental_fields=[CREATED_AT_INCREMENTAL, UPDATED_AT_INCREMENTAL],
    ),
    "submissions": JotformEndpointConfig(
        name="submissions",
        path="/user/submissions",
        primary_keys=["id"],
        partition_key="created_at",
        partition_format="month",
        default_incremental_field="created_at",
        incremental_fields=[CREATED_AT_INCREMENTAL, UPDATED_AT_INCREMENTAL],
    ),
    "reports": JotformEndpointConfig(
        name="reports",
        path="/user/reports",
        primary_keys=["id"],
        partition_key="created_at",
        partition_format="month",
    ),
    "questions": JotformEndpointConfig(
        name="questions",
        path="/form/{form_id}/questions",
        primary_keys=["form_id", "qid"],
        fan_out_over_forms=True,
    ),
}

ENDPOINTS = tuple(JOTFORM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in JOTFORM_ENDPOINTS.items() if config.incremental_fields
}
