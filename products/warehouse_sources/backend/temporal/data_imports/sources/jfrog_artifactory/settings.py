from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# AQL pages are requested with in-query .offset()/.limit(). 1000 rows keeps response bodies small
# while limiting round trips; the AQL server-side hard limit is far above this.
AQL_PAGE_SIZE = 1000


def _datetime_incremental_fields(*names: str) -> list[IncrementalField]:
    return [
        {
            "label": name,
            "type": IncrementalFieldType.DateTime,
            "field": name,
            "field_type": IncrementalFieldType.DateTime,
        }
        for name in names
    ]


@dataclass
class JfrogArtifactoryEndpointConfig:
    name: str
    # "rest" endpoints are a single unpaginated GET under /artifactory/api; "aql" endpoints POST an
    # AQL query to /artifactory/api/search/aql with in-body offset/limit pagination.
    kind: Literal["rest", "aql"]
    # REST only: path under /artifactory/api, e.g. "/repositories".
    path: str = ""
    # REST only: key of the row list in the response JSON; None when the response is a bare array.
    response_key: Optional[str] = None
    # AQL only: query domain ("items" or "builds").
    aql_domain: str = ""
    # AQL only: fields for .include(). Primary-domain fields only — AQL rejects
    # .sort()/.offset()/.limit() when .include() pulls fields from other domains.
    aql_fields: tuple[str, ...] = ()
    # AQL exposes server-side timestamp filters ({"modified":{"$gt":...}}); the REST list
    # endpoints here have none, so they stay full refresh.
    supports_incremental: bool = False
    # Also the sort/pagination field for full-refresh AQL runs, so page boundaries stay stable.
    default_incremental_field: str = "modified"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field to partition by. None when the resource has no creation timestamp.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["key"])
    should_sync_default: bool = True


JFROG_ARTIFACTORY_ENDPOINTS: dict[str, JfrogArtifactoryEndpointConfig] = {
    "repositories": JfrogArtifactoryEndpointConfig(
        name="repositories",
        kind="rest",
        path="/repositories",
        primary_keys=["key"],
    ),
    "artifacts": JfrogArtifactoryEndpointConfig(
        name="artifacts",
        kind="aql",
        aql_domain="items",
        # Non-admin AQL item queries must include repo, path, and name in the output.
        aql_fields=(
            "repo",
            "path",
            "name",
            "type",
            "size",
            "created",
            "created_by",
            "modified",
            "modified_by",
            "updated",
            "sha256",
            "actual_sha1",
            "actual_md5",
        ),
        supports_incremental=True,
        default_incremental_field="modified",
        incremental_fields=_datetime_incremental_fields("modified", "created"),
        partition_key="created",
        # An artifact is uniquely addressed by its repository + folder path + file name.
        primary_keys=["repo", "path", "name"],
    ),
    "builds": JfrogArtifactoryEndpointConfig(
        name="builds",
        kind="aql",
        aql_domain="builds",
        aql_fields=("name", "number", "created", "created_by", "modified", "modified_by", "url"),
        supports_incremental=True,
        default_incremental_field="created",
        incremental_fields=_datetime_incremental_fields("created"),
        partition_key="created",
        primary_keys=["name", "number"],
        # AQL build-domain queries need an admin user (or a token scoped to the builds domain),
        # so don't select this table by default for tokens that can't reach it.
        should_sync_default=False,
    ),
    "storage_summary": JfrogArtifactoryEndpointConfig(
        name="storage_summary",
        kind="rest",
        path="/storageinfo",
        response_key="repositoriesSummaryList",
        primary_keys=["repoKey"],
        # /api/storageinfo requires admin privileges.
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(JFROG_ARTIFACTORY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in JFROG_ARTIFACTORY_ENDPOINTS.items()
}
