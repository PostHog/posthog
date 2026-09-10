from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class JenkinsEndpointConfig:
    name: str
    incremental_fields: list[IncrementalField]
    # STABLE field used to partition the Delta table — never an updated_at style field, which would
    # rewrite partitions on every sync. None for endpoints with no stable timestamp (e.g. jobs).
    partition_key: Optional[str] = None
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_keys: list[str] = field(default_factory=lambda: ["url"])
    # True for endpoints that iterate one child request per discovered job (builds).
    fans_out_over_jobs: bool = False


# Jenkins exposes machine-readable data at any object's `/api/json`. There is no vendor-hosted
# instance and no cursor/page-token pagination — field selection and windowing use the `tree` query
# param (e.g. `tree=builds[number,result,timestamp]{0,100}`). The two streams a data team actually
# wants for DORA metrics are the job catalog and per-job build history.
#
# Jenkins has NO server-side "updated since" / timestamp filter on any endpoint. Builds are still
# synced incrementally because Jenkins returns a job's builds strictly newest-first and lets us
# window by index range, so we walk pages from the newest build and stop client-side as soon as we
# reach builds we've already synced (the `created_at` watermark) — a genuine bounded fetch, not a
# full-history re-walk. The job catalog itself has no stable cursor, so it is full refresh.
JENKINS_ENDPOINTS: dict[str, JenkinsEndpointConfig] = {
    "jobs": JenkinsEndpointConfig(
        name="jobs",
        # Jobs carry no creation timestamp, so there is no stable cursor or partition key. Discovery
        # recurses into Folders / Multibranch Pipelines, so the row set is the full flattened catalog.
        incremental_fields=[],
    ),
    "builds": JenkinsEndpointConfig(
        name="builds",
        # `timestamp` is the build's start time in epoch milliseconds and never changes once set. We
        # normalize it into a `created_at` ISO 8601 datetime on each row and both partition and sync
        # incrementally on that. A build's `result`/`duration` mutate after it first appears (a build
        # still running when synced), so a build that finishes after newer builds have landed won't be
        # re-fetched once it drops below the watermark — a full refresh re-pulls everything.
        partition_key="created_at",
        sort_mode="desc",
        fans_out_over_jobs=True,
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(JENKINS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in JENKINS_ENDPOINTS.items()
}
