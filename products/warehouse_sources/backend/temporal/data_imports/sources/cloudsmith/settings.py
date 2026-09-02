from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

CLOUDSMITH_BASE_URL = "https://api.cloudsmith.io/v1"

# Cloudsmith's list endpoints default to 30 results per page. 100 is the largest size the docs
# advertise, and it keeps the number of round trips down on repositories with many packages.
PAGE_SIZE = 100

# Cloudsmith reports the number of pages in a response header rather than the body, and returns
# 404 "Invalid page." for a page past the last one, so pagination has to stop on this header.
PAGE_TOTAL_HEADER = "X-Pagination-PageTotal"

UPLOADED_AT_INCREMENTAL: IncrementalField = {
    "label": "uploaded_at",
    "type": IncrementalFieldType.DateTime,
    "field": "uploaded_at",
    "field_type": IncrementalFieldType.DateTime,
}


@dataclass
class CloudsmithEndpointConfig:
    name: str
    path: str
    primary_key: str | list[str]
    # Query params sent on every request for this endpoint, on top of pagination. Used to pin an
    # explicit sort so page boundaries stay stable while rows are inserted mid-walk.
    params: dict[str, str] = field(default_factory=dict)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    # Stable creation-time field used for datetime partitioning. None where the resource has no
    # non-mutating creation timestamp.
    partition_key: str | None = None
    page_size: int = PAGE_SIZE
    # Only meaningful for an endpoint with incremental fields, since it drives when the pipeline
    # checkpoints the watermark. Every other endpoint here is full refresh, so the default is
    # inert for them rather than a claim about the order Cloudsmith returns rows in.
    sort_mode: Literal["asc", "desc"] = "asc"
    fanout: DependentEndpointConfig | None = None
    # Response fields dropped from every row before it is yielded.
    strip_fields: tuple[str, ...] = ()


# Every repository-scoped endpoint fans out from the workspace's repository list, binding the
# repository slug into `{repo}`. `{owner}` is pre-formatted from the configured workspace.
_REPOSITORY_FANOUT = DependentEndpointConfig(
    parent_name="repositories",
    resolve_param="repo",
    resolve_field="slug",
    include_from_parent=["slug"],
    # The framework injects the parent value as `_repositories_slug`; renaming it to
    # `repository_slug` gives every child table an explicit, stable parent column that does not
    # collide with a resource's own `repository` field.
    parent_field_renames={"slug": "repository_slug"},
    # Repositories are listed oldest-first so the parent walk is not reordered by activity
    # (`-created_at` is the API default, and `downloads`/`package_count` would shift mid-walk).
    parent_params={"sort": "created_at"},
)


CLOUDSMITH_ENDPOINTS: dict[str, CloudsmithEndpointConfig] = {
    "repositories": CloudsmithEndpointConfig(
        name="repositories",
        path="/repos/{owner}/",
        primary_key="slug_perm",
        params={"sort": "created_at"},
        partition_key="created_at",
    ),
    "packages": CloudsmithEndpointConfig(
        name="packages",
        path="/packages/{owner}/{repo}/",
        # `slug_perm` is Cloudsmith's permanent package identifier, but the docs only promise it
        # is unique within its repository, and this table aggregates packages from every
        # repository in the workspace — so the parent repository is part of the key.
        primary_key=["repository_slug", "slug_perm"],
        # `date` is the ascending form of the endpoint's `-date` default and sorts on upload
        # time, which never changes — so pages do not shift as new packages are uploaded.
        params={"sort": "date"},
        # The `query` search filter accepts `uploaded:>=<datetime>`, a real server-side filter
        # that bounds the pages fetched. It only tracks upload time: a package whose status,
        # download count or scan result changes later keeps its original `uploaded_at`, so
        # those updates need a full refresh.
        incremental_fields=[UPLOADED_AT_INCREMENTAL],
        default_incremental_field="uploaded_at",
        partition_key="uploaded_at",
        # Fan-out interleaves repositories, so rows are never globally ascending by
        # `uploaded_at` even though each repository's own page walk is. Declaring `desc` makes
        # the pipeline persist the incremental watermark only once the whole sync completes, so
        # a partial run cannot advance it past repositories it never reached.
        sort_mode="desc",
        fanout=_REPOSITORY_FANOUT,
    ),
    "entitlements": CloudsmithEndpointConfig(
        name="entitlements",
        path="/entitlements/{owner}/{repo}/",
        primary_key=["repository_slug", "slug_perm"],
        params={"sort": "name"},
        partition_key="created_at",
        fanout=_REPOSITORY_FANOUT,
        # `token` is the download credential the entitlement hands out. Cloudsmith only fills it
        # in when `show_tokens=true` (which we never send), but it is stripped anyway so a future
        # API default change cannot copy live credentials into a queryable warehouse table.
        strip_fields=("token",),
    ),
    "webhooks": CloudsmithEndpointConfig(
        name="webhooks",
        path="/webhooks/{owner}/{repo}/",
        primary_key=["repository_slug", "slug_perm"],
        partition_key="created_at",
        fanout=_REPOSITORY_FANOUT,
        # `target_url` can embed an auth token in its path, query or userinfo, and `templates`
        # carries the rendered request bodies - both are credentials a project member could
        # replay from a warehouse table, so neither is synced.
        strip_fields=("target_url", "templates"),
    ),
    "vulnerabilities": CloudsmithEndpointConfig(
        name="vulnerabilities",
        path="/vulnerabilities/{owner}/",
        primary_key="identifier",
        partition_key="created_at",
    ),
    "audit_log": CloudsmithEndpointConfig(
        name="audit_log",
        path="/audit-log/{owner}/",
        primary_key="uuid",
        partition_key="event_at",
    ),
    "members": CloudsmithEndpointConfig(
        name="members",
        path="/orgs/{owner}/members/",
        primary_key="user_id",
        params={"sort": "user_name"},
        partition_key="joined_at",
    ),
    "teams": CloudsmithEndpointConfig(
        name="teams",
        path="/orgs/{owner}/teams/",
        primary_key="slug_perm",
        params={"sort": "name"},
    ),
}

ENDPOINTS = tuple(CLOUDSMITH_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CLOUDSMITH_ENDPOINTS.items()
}
