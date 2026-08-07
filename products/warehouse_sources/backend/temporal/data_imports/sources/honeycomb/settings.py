from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


class HoneycombScope(Enum):
    """Where an endpoint lives in Honeycomb's resource hierarchy.

    A configuration API key is scoped to one Honeycomb environment. Some resources are
    environment-wide collections returned in a single request (datasets, boards, recipients);
    most are addressed per dataset (columns, triggers, SLOs, markers, …), so fetching those
    tables means fanning out one request per dataset. Burn alerts go one level deeper: they
    are listed per SLO, so the fan-out walks datasets -> SLOs -> burn alerts.
    """

    # Environment-wide collection returned by a single static path (GET /1/datasets).
    ENVIRONMENT = "environment"
    # Fan out over every dataset in the environment (GET /1/<resource>/{dataset_slug}).
    PER_DATASET = "per_dataset"
    # Fan out over every SLO in every dataset (GET /1/burn_alerts/{dataset_slug}?slo_id=…).
    PER_SLO = "per_slo"


@dataclass
class HoneycombEndpointConfig:
    name: str
    scope: HoneycombScope
    # Path template. PER_DATASET and PER_SLO paths contain ``{dataset_slug}``; ENVIRONMENT
    # paths are static.
    path: str
    # Primary key columns used for merge dedup. For fan-out children the dataset slug is
    # included (and injected into every row) so the key stays unique across the whole table —
    # Honeycomb documents ids per resource, not globally, and multi-dataset SLOs are listed
    # under each dataset they span.
    primary_keys: list[str]
    # Stable, creation-time datetime column to partition by. Never an `updated_at` style
    # field — those move and would rewrite partitions every sync. None disables partitioning.
    partition_key: Optional[str] = None
    # Also fetch the environment-wide pseudo-dataset ``__all__`` after the per-dataset fan-out.
    # Honeycomb keeps environment-scoped markers and derived columns under that keyword rather
    # than any real dataset, so skipping it would silently drop them.
    include_environment_wide: bool = False
    # The menu of incremental cursor candidates advertised to the user. Empty = full refresh
    # only — none of Honeycomb's v1 config endpoints expose a server-side timestamp filter.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Whether the table is selected for sync by default in the connection wizard.
    should_sync_default: bool = True


HONEYCOMB_ENDPOINTS: dict[str, HoneycombEndpointConfig] = {
    "datasets": HoneycombEndpointConfig(
        name="datasets",
        scope=HoneycombScope.ENVIRONMENT,
        path="/1/datasets",
        # Datasets have no id field; the slug is the unique identifier within an environment.
        primary_keys=["slug"],
        partition_key="created_at",
    ),
    "columns": HoneycombEndpointConfig(
        name="columns",
        scope=HoneycombScope.PER_DATASET,
        path="/1/columns/{dataset_slug}",
        primary_keys=["id", "dataset_slug"],
        partition_key="created_at",
    ),
    "derived_columns": HoneycombEndpointConfig(
        name="derived_columns",
        scope=HoneycombScope.PER_DATASET,
        path="/1/derived_columns/{dataset_slug}",
        primary_keys=["id", "dataset_slug"],
        partition_key="created_at",
        include_environment_wide=True,
    ),
    "slos": HoneycombEndpointConfig(
        name="slos",
        scope=HoneycombScope.PER_DATASET,
        path="/1/slos/{dataset_slug}",
        primary_keys=["id", "dataset_slug"],
        partition_key="created_at",
    ),
    "burn_alerts": HoneycombEndpointConfig(
        name="burn_alerts",
        scope=HoneycombScope.PER_SLO,
        path="/1/burn_alerts/{dataset_slug}",
        primary_keys=["id", "dataset_slug"],
        partition_key="created_at",
    ),
    "triggers": HoneycombEndpointConfig(
        name="triggers",
        scope=HoneycombScope.PER_DATASET,
        path="/1/triggers/{dataset_slug}",
        primary_keys=["id", "dataset_slug"],
        partition_key="created_at",
    ),
    "markers": HoneycombEndpointConfig(
        name="markers",
        scope=HoneycombScope.PER_DATASET,
        path="/1/markers/{dataset_slug}",
        primary_keys=["id", "dataset_slug"],
        partition_key="created_at",
        include_environment_wide=True,
    ),
    "boards": HoneycombEndpointConfig(
        name="boards",
        scope=HoneycombScope.ENVIRONMENT,
        path="/1/boards",
        # Boards carry no creation timestamp, so the table is unpartitioned.
        primary_keys=["id"],
    ),
    "recipients": HoneycombEndpointConfig(
        name="recipients",
        scope=HoneycombScope.ENVIRONMENT,
        path="/1/recipients",
        primary_keys=["id"],
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(HONEYCOMB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HONEYCOMB_ENDPOINTS.items()
}
