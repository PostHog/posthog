from dataclasses import dataclass, field
from typing import Any, Literal

from products.warehouse_sources.backend.types import IncrementalField

# The Hub caps list endpoints at 1000 rows per page; larger pages don't return more.
PAGE_SIZE = 1000

# Sort repo lists ascending by createdAt (immutable), so new repos append to the end and don't shift
# pages we've already walked mid-sync. `full=true` returns the richer object (e.g. pipeline_tag,
# library_name on models); harmless on endpoints that don't add fields.
REPO_LIST_PARAMS: dict[str, Any] = {"sort": "createdAt", "direction": 1, "limit": PAGE_SIZE, "full": "true"}

REPO_KINDS = ("models", "datasets", "spaces")


@dataclass(frozen=True)
class HuggingFaceEndpointConfig:
    name: str
    path: str
    # createdAt is immutable, so it's a stable partition key (unlike lastModified). None for
    # endpoints whose rows carry no creation time.
    partition_key: str | None = "createdAt"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Query param that scopes the endpoint to the connected namespace. None when the namespace sits
    # in the path or the endpoint is Hub-wide.
    author_param: str | None = "author"
    params: dict[str, Any] = field(default_factory=lambda: dict(REPO_LIST_PARAMS))
    # "list" pages a list endpoint, "tags" flattens a tags-by-type lookup, "discussions" fans out
    # over every repo of the namespace.
    kind: Literal["list", "tags", "discussions"] = "list"
    # Endpoints that filter rows after paging (likes, collections) can return a short or empty page
    # while a next link remains, so they must follow the Link header to its end.
    stop_on_empty_page: bool = True
    # Lift the nested `repo: {name, type}` to top-level columns so they can form the primary key.
    flatten_repo: bool = False
    # Treat a 404 as an empty table rather than a failed sync.
    ignore_not_found: bool = False


HUGGING_FACE_ENDPOINTS: dict[str, HuggingFaceEndpointConfig] = {
    "models": HuggingFaceEndpointConfig(name="models", path="/api/models"),
    "datasets": HuggingFaceEndpointConfig(name="datasets", path="/api/datasets"),
    "spaces": HuggingFaceEndpointConfig(name="spaces", path="/api/spaces"),
    "discussions": HuggingFaceEndpointConfig(
        name="discussions",
        path="/api/{repo_kind}/{repo_id}/discussions",
        # `num` is only unique within a repo.
        primary_keys=["repo_type", "repo_name", "num"],
        # The namespace scopes the repo listing the fan-out walks; on this endpoint `author` would
        # filter by discussion author instead.
        author_param=None,
        params={},
        kind="discussions",
        flatten_repo=True,
    ),
    "collections": HuggingFaceEndpointConfig(
        name="collections",
        path="/api/collections",
        partition_key=None,
        primary_keys=["slug"],
        author_param="owner",
        params={"sort": "lastModified", "limit": 100},
        stop_on_empty_page=False,
    ),
    "likes": HuggingFaceEndpointConfig(
        name="likes",
        path="/api/users/{author}/likes",
        primary_keys=["repo_type", "repo_name"],
        author_param=None,
        params={"limit": PAGE_SIZE},
        stop_on_empty_page=False,
        flatten_repo=True,
        # Likes only exist for users, so an organization namespace answers 404.
        ignore_not_found=True,
    ),
    "model_tags": HuggingFaceEndpointConfig(
        name="model_tags",
        path="/api/models-tags-by-type",
        partition_key=None,
        primary_keys=["type", "id"],
        author_param=None,
        params={},
        kind="tags",
    ),
    "dataset_tags": HuggingFaceEndpointConfig(
        name="dataset_tags",
        path="/api/datasets-tags-by-type",
        partition_key=None,
        primary_keys=["type", "id"],
        author_param=None,
        params={},
        kind="tags",
    ),
}

ENDPOINTS = tuple(HUGGING_FACE_ENDPOINTS.keys())

# The Hub has no server-side timestamp range filter (it silently ignores `since`), so every endpoint
# is full refresh only. Repo metadata (likes, downloads, lastModified) mutates in place, so
# append-only would drop updates — hence no incremental/append fields for any endpoint.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
