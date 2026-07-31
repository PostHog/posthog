from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField

# Unstructured's Platform API paths always carry a trailing slash; hitting them without it returns a
# 307 redirect (which also downgrades the scheme), so keep the slash to talk to the API directly.


@dataclass
class UnstructuredEndpointConfig:
    name: str
    path: str
    # Field to partition Delta files by. Must be stable (never rewritten upstream) so partitions
    # don't churn every sync; `created_at` is set once at object creation across every resource here.
    partition_key: str | None = "created_at"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Only /workflows/ accepts page / page_size; the other list endpoints return the full array in a
    # single response, so pagination (and resume) only applies to workflows.
    paginated: bool = False
    should_sync_default: bool = True
    # Top-level fields dropped from every row before it is yielded. The /sources/ and /destinations/
    # connector `config` object embeds raw secrets (DB passwords, OAuth refresh tokens, cloud access
    # keys), so it must never be persisted to a warehouse table where any project member with query
    # access could read it back. We drop the whole object rather than allowlisting because the fields
    # vary per connector type and a new type could introduce a secret we don't yet know to strip.
    drop_fields: tuple[str, ...] = ()


UNSTRUCTURED_ENDPOINTS: dict[str, UnstructuredEndpointConfig] = {
    "workflows": UnstructuredEndpointConfig(name="workflows", path="/api/v1/workflows/", paginated=True),
    "jobs": UnstructuredEndpointConfig(name="jobs", path="/api/v1/jobs/"),
    "sources": UnstructuredEndpointConfig(name="sources", path="/api/v1/sources/", drop_fields=("config",)),
    "destinations": UnstructuredEndpointConfig(
        name="destinations", path="/api/v1/destinations/", drop_fields=("config",)
    ),
}

ENDPOINTS = tuple(UNSTRUCTURED_ENDPOINTS.keys())

# All four endpoints ship as full refresh. Only /workflows/ exposes a server-side timestamp filter
# (`created_since`); jobs, sources, and destinations have no server-side time filter at all (confirmed
# against the Platform API OpenAPI spec), so a "since" sync would still page the whole list and isn't
# genuinely incremental. Workflows, sources, and destinations are also low-volume mutable config
# inventory where a full refresh yields the correct current state (status/schedule edits included),
# which incremental-on-created_at would freeze. See the module docstring in `unstructured.py`.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
