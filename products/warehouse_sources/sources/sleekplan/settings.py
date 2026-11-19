from dataclasses import dataclass, field
from typing import Any, Literal

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    ResponseAction,
    incremental_field,
)

SLEEKPLAN_BASE_URL = "https://api.sleekplan.com/v1"
# `/v2` sits alongside `/v1` rather than replacing it, and the same key authenticates both. Groups
# and documents only exist there. Its pages are zero-based, where `/v1` starts at 1.
SLEEKPLAN_V2_BASE_URL = "https://api.sleekplan.com/v2"
V1_FIRST_PAGE = 1
V2_FIRST_PAGE = 0

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


# A `/v2` feature that the workspace's plan does not include answers HTTP 200 with
# `{"status": "error", "data": {"code": "upgrade_required"}}`. Without this action the selector
# matches nothing and the table syncs zero rows with no error.
PLAN_UPGRADE_REQUIRED_MESSAGE = (
    "Your Sleekplan plan does not include this data (upgrade_required). "
    "Upgrade your Sleekplan plan to sync this table, or turn the table off."
)
V2_RESPONSE_ACTIONS: list[ResponseAction] = [
    {
        "json_field": "data.code",
        "json_values": ["upgrade_required"],
        "action": "raise",
        "message": PLAN_UPGRADE_REQUIRED_MESSAGE,
    },
]

# Members are listed per group, so they fan out over /groups. `sort=created` ascending keeps the
# parent walk stable: groups added mid-walk land at the end.
_GROUP_PARENT_PARAMS = {"sort": "created", "sort_dir": "asc"}

GROUP_MEMBERS_FANOUT = DependentEndpointConfig(
    parent_name="Groups",
    resolve_param="group_id",
    resolve_field="group_id",
    include_from_parent=["group_id"],
    parent_field_renames={"group_id": "group_id"},
    parent_params=_GROUP_PARENT_PARAMS,
    # A group deleted between the parent listing and its member fetch answers 404.
    child_response_actions=[{"status_code": 404, "action": "ignore"}, *V2_RESPONSE_ACTIONS],
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
    base_url: str = SLEEKPLAN_BASE_URL
    first_page: int = V1_FIRST_PAGE
    response_actions: list[ResponseAction] = field(default_factory=list)


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
    # `/v2` returns `items` as an array, where `/v1` keys them by id.
    "Groups": SleekplanEndpointConfig(
        name="Groups",
        path="/groups",
        data_selector="data.items",
        primary_key=["group_id"],
        params=_GROUP_PARENT_PARAMS,
        partition_key="created",
        base_url=SLEEKPLAN_V2_BASE_URL,
        first_page=V2_FIRST_PAGE,
        response_actions=V2_RESPONSE_ACTIONS,
    ),
    # A user can belong to several groups, so the group id is part of the key.
    "GroupMembers": SleekplanEndpointConfig(
        name="GroupMembers",
        path="/groups/{group_id}/members",
        data_selector="data.items",
        primary_key=["group_id", "user_id"],
        base_url=SLEEKPLAN_V2_BASE_URL,
        first_page=V2_FIRST_PAGE,
        fanout=GROUP_MEMBERS_FANOUT,
    ),
    # The list takes no sort param and returns the newest change first. It leaves out `content`,
    # which only the per-document endpoint returns (up to 2 MB each).
    "Documents": SleekplanEndpointConfig(
        name="Documents",
        path="/documents",
        data_selector="data.items",
        primary_key=["document_id"],
        partition_key="created",
        base_url=SLEEKPLAN_V2_BASE_URL,
        first_page=V2_FIRST_PAGE,
        response_actions=V2_RESPONSE_ACTIONS,
    ),
}

ENDPOINTS = tuple(SLEEKPLAN_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SLEEKPLAN_ENDPOINTS.items()
}

# The survey endpoints re-read a trailing window each run, so appending would duplicate rows.
MERGE_ONLY_ENDPOINTS = ("Satisfaction", "Promoter")
