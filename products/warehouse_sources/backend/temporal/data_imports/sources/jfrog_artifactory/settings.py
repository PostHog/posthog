from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# AQL pages are requested with in-query .offset()/.limit(). 1000 rows keeps response bodies small
# while limiting round trips; the AQL server-side hard limit is far above this.
AQL_PAGE_SIZE = 1000

# Xray's v1 violations API defaults to 25 rows per page and doesn't document a maximum.
XRAY_PAGE_SIZE = 100


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


@dataclass(frozen=True)
class JfrogArtifactoryEndpointConfig:
    name: str
    # "rest" endpoints are a single unpaginated GET under /artifactory/api; "aql" endpoints POST an
    # AQL query to /artifactory/api/search/aql with in-body offset/limit pagination. "aql_related"
    # endpoints page the primary domain the same way, then fetch related-domain fields (stats,
    # modules, promotions) for each chunk of that page in a second, unpaginated query, because AQL
    # ignores .sort()/.offset()/.limit() once .include() names a related domain. "xray" is the
    # Xray v1 violations search.
    kind: Literal["rest", "aql", "aql_related", "xray"]
    # REST only: path under /artifactory/api, e.g. "/repositories".
    path: str = ""
    # REST only: key of the row list in the response JSON; None when the response is a bare array.
    response_key: Optional[str] = None
    # AQL only: query domain ("items" or "builds").
    aql_domain: str = ""
    # AQL only: fields for .include(). Primary-domain fields only — AQL rejects
    # .sort()/.offset()/.limit() when .include() pulls fields from other domains.
    aql_fields: tuple[str, ...] = ()
    # AQL only: static criteria merged into the primary-domain .find(). Related-domain criteria are
    # allowed here; only .include() is limited to the primary domain.
    aql_criteria: dict[str, Any] = field(default_factory=dict)
    # aql_related only: primary-domain fields that identify a parent row in the related query.
    aql_key_fields: tuple[str, ...] = ()
    # aql_related only: related-domain fields for the second query's .include().
    aql_related_fields: tuple[str, ...] = ()
    # aql_related only: nested (list key, domain) levels to walk in the related query's output,
    # e.g. (("modules", "module"), ("artifacts", "artifact")). One row is emitted per leaf entry.
    aql_related_path: tuple[tuple[str, str], ...] = ()
    # aql_related only: prefix for parent fields in emitted rows, e.g. "build_" -> build_name.
    parent_field_prefix: str = ""
    # aql_related only: parents per related query. Kept small where one parent fans out to many
    # rows so a related response stays well under MAX_RESPONSE_BYTES.
    aql_related_chunk_size: int = 100
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
    "artifact_statistics": JfrogArtifactoryEndpointConfig(
        name="artifact_statistics",
        kind="aql_related",
        aql_domain="items",
        aql_fields=("repo", "path", "name", "created"),
        # Only artifacts that have been downloaded carry download statistics.
        aql_criteria={"stat.downloads": {"$gt": 0}},
        aql_key_fields=("repo", "path", "name"),
        aql_related_fields=(
            "stat.downloads",
            "stat.downloaded",
            "stat.downloaded_by",
            "stat.remote_downloads",
            "stat.remote_downloaded",
            "stat.remote_downloaded_by",
        ),
        aql_related_path=(("stats", "stat"),),
        aql_related_chunk_size=250,
        # Download stats change on every download and AQL can't sort by a related-domain field,
        # so there is no ascending cursor to sync incrementally on.
        default_incremental_field="created",
        primary_keys=["repo", "path", "name"],
    ),
    "build_artifacts": JfrogArtifactoryEndpointConfig(
        name="build_artifacts",
        kind="aql_related",
        aql_domain="builds",
        aql_fields=("name", "number", "created"),
        aql_key_fields=("name", "number"),
        aql_related_fields=(
            "module.name",
            "module.artifact.name",
            "module.artifact.type",
            "module.artifact.sha1",
            "module.artifact.md5",
        ),
        aql_related_path=(("modules", "module"), ("artifacts", "artifact")),
        parent_field_prefix="build_",
        aql_related_chunk_size=10,
        # Build-info is immutable once published, so a build's artifacts never change after its
        # creation time.
        supports_incremental=True,
        default_incremental_field="created",
        incremental_fields=_datetime_incremental_fields("build_created"),
        partition_key="build_created",
        primary_keys=["build_name", "build_number", "module_name", "name"],
        should_sync_default=False,
    ),
    "build_dependencies": JfrogArtifactoryEndpointConfig(
        name="build_dependencies",
        kind="aql_related",
        aql_domain="builds",
        aql_fields=("name", "number", "created"),
        aql_key_fields=("name", "number"),
        aql_related_fields=(
            "module.name",
            "module.dependency.name",
            "module.dependency.scope",
            "module.dependency.type",
            "module.dependency.sha1",
            "module.dependency.md5",
        ),
        aql_related_path=(("modules", "module"), ("dependencies", "dependency")),
        parent_field_prefix="build_",
        aql_related_chunk_size=10,
        supports_incremental=True,
        default_incremental_field="created",
        incremental_fields=_datetime_incremental_fields("build_created"),
        partition_key="build_created",
        primary_keys=["build_name", "build_number", "module_name", "name"],
        should_sync_default=False,
    ),
    "build_promotions": JfrogArtifactoryEndpointConfig(
        name="build_promotions",
        kind="aql_related",
        aql_domain="builds",
        aql_fields=("name", "number", "created"),
        aql_key_fields=("name", "number"),
        aql_related_fields=(
            "promotion.created",
            "promotion.created_by",
            "promotion.status",
            "promotion.repo",
            "promotion.comment",
            "promotion.user",
        ),
        aql_related_path=(("promotions", "promotion"),),
        parent_field_prefix="build_",
        # Old builds get promoted long after they're created, so a cursor on the build's creation
        # time would miss new promotions. Full refresh only.
        default_incremental_field="created",
        partition_key="created",
        primary_keys=["build_name", "build_number", "created", "status"],
        should_sync_default=False,
    ),
    "xray_violations": JfrogArtifactoryEndpointConfig(
        name="xray_violations",
        kind="xray",
        path="/v1/violations",
        supports_incremental=True,
        default_incremental_field="created",
        incremental_fields=_datetime_incremental_fields("created"),
        partition_key="created",
        # A violation is one issue on one component under one watch; the details URL encodes all three
        # (watch_id, issue_id, comp_id) and is the only per-violation identifier the API returns.
        primary_keys=["violation_details_url"],
        # Needs JFrog Xray, which not every instance has.
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
