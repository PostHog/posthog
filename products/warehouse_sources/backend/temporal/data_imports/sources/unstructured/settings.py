from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Paths match the Platform API spec exactly: collection paths carry a trailing slash, and the per-job
# and notification paths do not. A collection path without its slash returns a 307 redirect (which
# also downgrades the scheme), so keep each path as the spec writes it.


@dataclass(frozen=True)
class UnstructuredEndpointConfig:
    name: str
    path: str
    # Field to partition Delta files by. Must be stable (never rewritten upstream) so partitions
    # don't churn every sync; `created_at` is set once at object creation across every resource here.
    # The per-job tables carry no timestamp of their own, so they partition on the parent job's.
    partition_key: str | None = "created_at"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Only /workflows/ accepts page / page_size. /notifications and the per-job failed files have their
    # own cursor and offset paging; the other list endpoints return the full array in one response.
    paginated: bool = False
    should_sync_default: bool = True
    # Top-level fields dropped from every row before it is yielded. The /sources/ and /destinations/
    # connector `config` object embeds raw secrets (DB passwords, OAuth refresh tokens, cloud access
    # keys), so it must never be persisted to a warehouse table where any project member with query
    # access could read it back. We drop the whole object rather than allowlisting because the fields
    # vary per connector type and a new type could introduce a secret we don't yet know to strip.
    drop_fields: tuple[str, ...] = ()
    # Per-job endpoints: list /jobs/ first, then call `path` (with a `{job_id}` placeholder) once per job.
    fan_out_jobs: bool = False
    sort_mode: Literal["asc", "desc"] = "asc"


UNSTRUCTURED_ENDPOINTS: dict[str, UnstructuredEndpointConfig] = {
    "workflows": UnstructuredEndpointConfig(name="workflows", path="/api/v1/workflows/", paginated=True),
    "jobs": UnstructuredEndpointConfig(name="jobs", path="/api/v1/jobs/"),
    "sources": UnstructuredEndpointConfig(name="sources", path="/api/v1/sources/", drop_fields=("config",)),
    "destinations": UnstructuredEndpointConfig(
        name="destinations", path="/api/v1/destinations/", drop_fields=("config",)
    ),
    # One request per job on every sync, so it is off by default to keep the request volume opt-in.
    "job_details": UnstructuredEndpointConfig(
        name="job_details",
        path="/api/v1/jobs/{job_id}/details",
        partition_key="job_created_at",
        fan_out_jobs=True,
        should_sync_default=False,
    ),
    # A job reports each failure once per file and workflow node, so neither field is unique alone.
    "job_failed_files": UnstructuredEndpointConfig(
        name="job_failed_files",
        path="/api/v1/jobs/{job_id}/failed-files",
        partition_key="job_created_at",
        primary_keys=["job_id", "node_id", "document"],
        fan_out_jobs=True,
    ),
    # The API returns notifications newest first and accepts no sort parameter.
    "notifications": UnstructuredEndpointConfig(name="notifications", path="/api/v1/notifications", sort_mode="desc"),
}

ENDPOINTS = tuple(UNSTRUCTURED_ENDPOINTS.keys())

# Only notifications sync incrementally: they are an append-only event log with a server-side `since`
# filter on `created_at`. /workflows/ also has a `created_since` filter, but workflows, sources, and
# destinations are low-volume mutable config inventory where a full refresh yields the correct current
# state (status/schedule edits included), which incremental-on-created_at would freeze. Jobs and the
# per-job tables have no server-side time filter at all (confirmed against the Platform API OpenAPI
# spec), so a "since" sync would still page the whole list. See the module docstring in `unstructured.py`.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "notifications": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
