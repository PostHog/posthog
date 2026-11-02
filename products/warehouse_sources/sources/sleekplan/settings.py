from dataclasses import dataclass, field
from typing import Any, Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

SLEEKPLAN_BASE_URL = "https://api.sleekplan.com/v1"

# Every list endpoint caps `per_page` at 100.
MAX_PAGE_SIZE = 100

# The survey endpoints take `date_start`/`date_end`, and the docs don't name the column they filter
# on. Sleekplan also replaces a satisfaction response within 30 days (a promoter response within 14)
# rather than appending a new one, so a record can change after its date. Re-reading a trailing
# window on every incremental run covers both; the merge upsert dedupes what comes back twice.
SURVEY_LOOKBACK_DAYS = 30
SURVEY_START_PARAM = "date_start"

# Comments and votes are addressed per post (/post/{postid}/...), so both fan out over /posts.
# `sort=new` is the closest thing to a stable parent ordering the endpoint offers: its other sort
# options (trend, top, scoring, priority) are recomputed values that can reshuffle mid-walk.
_POST_PARENT_PARAMS = {"sort": "new"}

# `sort=old` walks a post's children oldest first, so rows added mid-walk land at the end instead of
# shifting the pages behind them. Child request params live here rather than on the endpoint config:
# the fan-out helper builds the child request, so it is the only thing that reads them.
POST_COMMENTS_FANOUT = DependentEndpointConfig(
    parent_name="Posts",
    resolve_param="postid",
    resolve_field="feedback_id",
    include_from_parent=["feedback_id"],
    parent_field_renames={"feedback_id": "feedback_id"},
    parent_params=_POST_PARENT_PARAMS,
    child_params={"sort": "old"},
)

POST_VOTES_FANOUT = DependentEndpointConfig(
    parent_name="Posts",
    resolve_param="postid",
    resolve_field="feedback_id",
    include_from_parent=["feedback_id"],
    parent_field_renames={"feedback_id": "feedback_id"},
    parent_params=_POST_PARENT_PARAMS,
    child_params={"sort": "old", "filter": "all"},
)


@dataclass(frozen=False)
class SleekplanEndpointConfig:
    name: str
    path: str
    data_selector: str
    primary_key: list[str]
    page_size: int = MAX_PAGE_SIZE
    params: dict[str, Any] = field(default_factory=dict)
    partition_key: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    # "asc" only where the endpoint takes a sort param we can pin to an ascending, immutable
    # column. Everything else stays "desc" so the incremental watermark is only written once the
    # run finishes, rather than being checkpointed against an order we cannot guarantee.
    sort_mode: Literal["asc", "desc"] = "desc"
    fanout: DependentEndpointConfig | None = None


SLEEKPLAN_ENDPOINTS: dict[str, SleekplanEndpointConfig] = {
    # Sorted ascending by creation date so rows added while we page don't shift earlier pages.
    "Users": SleekplanEndpointConfig(
        name="Users",
        path="/users",
        data_selector="data.items.*",
        primary_key=["user_id"],
        params={"sort": "created", "sort_dir": "ASC"},
        partition_key="created",
        sort_mode="asc",
    ),
    "Posts": SleekplanEndpointConfig(
        name="Posts",
        path="/posts",
        data_selector="data.items.*",
        primary_key=["feedback_id"],
        params=_POST_PARENT_PARAMS,
        partition_key="created",
    ),
    # `comment_id` looks workspace-wide, but the docs never say so, so the post id stays in the key:
    # a per-post id would collide across posts and seed duplicate rows.
    "Comments": SleekplanEndpointConfig(
        name="Comments",
        path="/post/{postid}/comments",
        data_selector="data.comments.*",
        primary_key=["feedback_id", "comment_id"],
        partition_key="created",
        sort_mode="asc",
        fanout=POST_COMMENTS_FANOUT,
    ),
    # A vote carries no id of its own; it is one user's vote on one post, so that pair is the key.
    "Votes": SleekplanEndpointConfig(
        name="Votes",
        path="/post/{postid}/votes",
        data_selector="data.votes",
        primary_key=["feedback_id", "user_id"],
        partition_key="created",
        sort_mode="asc",
        fanout=POST_VOTES_FANOUT,
    ),
    "Updates": SleekplanEndpointConfig(
        name="Updates",
        path="/updates",
        data_selector="data.items.*",
        primary_key=["changelog_id"],
        partition_key="created",
    ),
    # `updated` is the only timestamp on a satisfaction response, which also rules it out as a
    # partition key (partitions would be rewritten every time a response is replaced).
    "Satisfaction": SleekplanEndpointConfig(
        name="Satisfaction",
        path="/satisfaction",
        data_selector="data",
        primary_key=["satisfaction_id"],
        incremental_fields=[incremental_field("updated")],
        default_incremental_field="updated",
    ),
    "Promoter": SleekplanEndpointConfig(
        name="Promoter",
        path="/promoter",
        data_selector="data",
        primary_key=["promoter_id"],
        partition_key="created",
        incremental_fields=[incremental_field("updated")],
        default_incremental_field="updated",
    ),
}

ENDPOINTS = tuple(SLEEKPLAN_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SLEEKPLAN_ENDPOINTS.items()
}

# The survey endpoints re-read a trailing window each run, so appending would duplicate rows.
MERGE_ONLY_ENDPOINTS = ("Satisfaction", "Promoter")
