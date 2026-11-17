from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType


@dataclass(frozen=False)
class TravisCIEndpointConfig:
    name: str
    # Path template relative to the API base. Fan-out endpoints carry a ``{repository_id}``
    # placeholder filled per repository.
    path: str
    # Key holding the row list in the JSON response (Travis v3 wraps collections, e.g.
    # ``{"builds": [...], "@pagination": {...}}``).
    collection_key: str
    # Iterate every accessible repository and query ``path`` once per repo.
    fan_out_over_repositories: bool = False
    # Yield the rows nested under this key of each collection item (e.g. a build's ``jobs``)
    # instead of the items themselves, tagged with the parent item's id as ``build_id``.
    embedded_collection_key: Optional[str] = None
    # Extra query params sent on the first page request (``@pagination.next`` hrefs carry
    # them forward on subsequent pages).
    extra_params: dict[str, str] = field(default_factory=dict)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Field used to partition the Delta table. Must be STABLE (set once at creation) — never
    # ``updated_at``/``started_at`` style fields, which mutate on restarts and would rewrite
    # partitions on every sync.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


# Travis CI API v3 endpoints. Builds expose no server-side timestamp filter, but they accept
# ``sort_by`` and return monotonically increasing ids, so builds, jobs and stages sync
# incrementally by paginating newest-first (``sort_by=id:desc``, verified against the live
# API) and stopping once a page reaches the last-synced id watermark. Requests do the same.
TRAVIS_CI_ENDPOINTS: dict[str, TravisCIEndpointConfig] = {
    "repositories": TravisCIEndpointConfig(
        name="repositories",
        path="/repos",
        collection_key="repositories",
        # Repositories expose no creation timestamp, so no partitioning or incremental sync.
    ),
    "builds": TravisCIEndpointConfig(
        name="builds",
        path="/repo/{repository_id}/builds",
        collection_key="builds",
        fan_out_over_repositories=True,
        extra_params={"sort_by": "id:desc"},
        # Build ids are global (not per-repo), so the id watermark holds across the fan-out.
        # A build's state/finished_at mutate after it first appears; once it drops below the
        # watermark it isn't re-fetched — a full refresh re-pulls final states.
        incremental_fields=[
            {
                "label": "id",
                "type": IncrementalFieldType.Integer,
                "field": "id",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        # Builds expose no immutable creation timestamp (started_at resets on restart), so no
        # partitioning.
    ),
    "jobs": TravisCIEndpointConfig(
        name="jobs",
        path="/repo/{repository_id}/builds",
        collection_key="builds",
        fan_out_over_repositories=True,
        embedded_collection_key="jobs",
        # ``include=build.jobs`` promotes each build's embedded jobs to their standard
        # representation, so jobs ride the builds pagination (1 request per 100 builds)
        # instead of one request per build.
        extra_params={"sort_by": "id:desc", "include": "build.jobs"},
        # The watermark is the parent build id (injected as ``build_id``): a page of builds
        # with no jobs still advances the cursor deterministically, which a job-id watermark
        # can't guarantee.
        incremental_fields=[
            {
                "label": "build_id",
                "type": IncrementalFieldType.Integer,
                "field": "build_id",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        partition_key="created_at",
    ),
    "stages": TravisCIEndpointConfig(
        name="stages",
        path="/repo/{repository_id}/builds",
        collection_key="builds",
        fan_out_over_repositories=True,
        # Builds already embed their stages (every documented stage attribute except the job
        # list), so stages ride the builds pagination instead of one ``/build/{id}/stages``
        # request per build.
        embedded_collection_key="stages",
        extra_params={"sort_by": "id:desc"},
        incremental_fields=[
            {
                "label": "build_id",
                "type": IncrementalFieldType.Integer,
                "field": "build_id",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        # Stages expose no creation timestamp (started_at resets on restart), so no partitioning.
    ),
    "requests": TravisCIEndpointConfig(
        name="requests",
        path="/repo/{repository_id}/requests",
        collection_key="requests",
        fan_out_over_repositories=True,
        # The endpoint has no ``sort_by`` but always orders by id descending, and request ids are
        # global, so it syncs incrementally the same way as builds.
        incremental_fields=[
            {
                "label": "id",
                "type": IncrementalFieldType.Integer,
                "field": "id",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        partition_key="created_at",
    ),
    "crons": TravisCIEndpointConfig(
        name="crons",
        path="/repo/{repository_id}/crons",
        collection_key="crons",
        fan_out_over_repositories=True,
        partition_key="created_at",
        # Full refresh only, one walk per repository each sync, like branches.
        should_sync_default=False,
    ),
    "branches": TravisCIEndpointConfig(
        name="branches",
        path="/repo/{repository_id}/branches",
        collection_key="branches",
        fan_out_over_repositories=True,
        # Branches carry no id; the name is only unique within a repository.
        primary_keys=["repository_id", "name"],
        # Full refresh only, and it re-walks every repo's branch list each sync — off by
        # default to avoid the API cost for users who don't need it.
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(TRAVIS_CI_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TRAVIS_CI_ENDPOINTS.items() if config.incremental_fields
}
