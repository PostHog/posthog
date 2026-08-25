from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How a list endpoint is walked:
# - "cursor": a `cursor` request param fed from a next-page response field.
# - "page":   `page`/`page_size` request params, terminating on the response's total.
# - "offset": `limit`/`offset` request params, terminating on the response's total.
# - "single": one request returns the whole list, no pagination params.
PaginationMode = Literal["cursor", "page", "offset", "single"]

# Format of the value an endpoint's `incremental_param` takes. Decagon is not internally
# consistent across endpoints: the exports take epoch seconds, and /admin_log/get types
# its bounds loosely. Confirm per endpoint rather than generalizing.
IncrementalParamFormat = Literal["epoch_seconds", "iso8601"]

# Decagon's export reference names the conversations next-page response field three
# different ways: `next_page_cursor` in the parameter prose, `next_cursor` in the official
# example code, and `next_page_updated_after` in the example response. Production
# responses carry no usable `next_page_cursor` (reading only that name made the walk stop
# after one page), so accept every documented name. All of them feed the same `cursor`
# request param.
CONVERSATIONS_NEXT_CURSOR_KEYS = ("next_page_cursor", "next_cursor", "next_page_updated_after")


@dataclass
class DecagonEndpointConfig:
    name: str
    path: str
    # Top-level key in the JSON response that holds the list of rows
    # (e.g. `{"conversations": [...]}` -> `"conversations"`).
    data_key: str
    # None for streams with no documented unique id: they sync append-only, because a
    # guessed composite key that turned out non-unique would silently merge distinct rows.
    primary_keys: Optional[list[str]]
    incremental_fields: list[IncrementalField]
    pagination: PaginationMode
    # "cursor" mode: response fields that may carry the next-page cursor, tried in order.
    next_cursor_keys: Optional[tuple[str, ...]] = None
    # "cursor" mode: response field signalling whether more pages exist. When set, a falsy
    # value ends the walk even if a cursor is present. None means the null cursor alone
    # ends the walk.
    has_more_key: Optional[str] = None
    # "page"/"offset" modes: rows requested per page. None sends no size param and leaves
    # the server default, in which case only an empty page ends the walk.
    page_size: Optional[int] = None
    # "page"/"offset" modes: response field carrying the total row count.
    total_key: Optional[str] = None
    # Stable datetime field used for partitioning, or None for tables with no timestamp.
    # Must never change for a row (so `created_at`, never `updated_at`).
    partition_key: Optional[str] = None
    # Server-side query param that lower-bounds the incremental field, and the format its
    # value takes. None means the endpoint has no server-side filter, so no incremental
    # sync should be advertised for it.
    incremental_param: Optional[str] = None
    incremental_param_format: IncrementalParamFormat = "epoch_seconds"
    # Whether the endpoint 400s on a request that omits incremental_param entirely (as
    # opposed to treating it as an optional filter). A full refresh, or the first run of
    # an incremental sync, has no window to send; when this is set, the walker falls back
    # to the epoch so every such request still carries a bound.
    incremental_param_required: bool = False
    # Param selecting which timestamp the bounds apply to (/conversation/export only).
    timestamp_filter_param: Optional[str] = None
    # Static query params always sent.
    extra_params: dict[str, str] = field(default_factory=dict)
    # Order rows arrive in when the endpoint documents one. "desc" is also the safe
    # declaration for endpoints whose order is undocumented: the pipeline then defers the
    # incremental watermark to the end of a successful run instead of checkpointing
    # mid-run, so a wrong guess cannot make a resumed sync skip rows.
    sort_mode: Literal["asc", "desc"] = "asc"
    # Whether the append sync type is offered alongside incremental. Streams whose rows
    # mutate in place must leave this False: appends would accumulate one copy per
    # mutation, and only a merge keeps the table at one row per primary key.
    supports_append: bool = False
    # Whether the table is selected by default on a new source. False for tables that
    # fan out row counts or sync data a team should opt into deliberately.
    should_sync_default: bool = True
    # Batcher overrides for endpoints whose rows are large (whole documents), so the
    # source-to-Arrow conversion does not materialize an oversized table. None keeps the
    # pipeline defaults.
    chunk_size: Optional[int] = None
    chunk_size_bytes: Optional[int] = None


# Decagon's per-endpoint contracts differ enough that everything rides this catalog: four
# pagination styles, per-endpoint primary keys and partitioning, and incremental filters
# whose param names and value formats vary by endpoint.
DECAGON_ENDPOINTS: dict[str, DecagonEndpointConfig] = {
    # /conversation/export returns conversations with their messages, CSAT ratings, tags,
    # and metadata, up to 100 per page. It accepts min_timestamp/max_timestamp filters
    # (epoch seconds), with `timestamp_filter` selecting the field they bound: created_at
    # (the default), updated_at, or last_message_time. Rows always carry `updated_at`
    # (ISO 8601), so the stream syncs incrementally by filtering on updated_at and merging
    # on conversation_id. A conversation re-enters the export whenever it receives new
    # messages, which is why the vendor recommends upserting on conversation_id rather
    # than appending.
    "conversations": DecagonEndpointConfig(
        name="conversations",
        path="/conversation/export",
        data_key="conversations",
        primary_keys=["conversation_id"],
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        pagination="cursor",
        next_cursor_keys=CONVERSATIONS_NEXT_CURSOR_KEYS,
        partition_key="created_at",
        incremental_param="min_timestamp",
        incremental_param_format="epoch_seconds",
        timestamp_filter_param="timestamp_filter",
        # The export documents `order` with an asc default, walking oldest to newest.
        sort_mode="asc",
        # A conversation row mutates in place whenever new messages arrive.
        supports_append=False,
    ),
    # /agent_assist/actions/export records every Agent Assist action a human support
    # agent performed. It pages on next_cursor/has_more, which is a different contract
    # from the conversations export. Events document no unique id, so the stream syncs
    # append-only (windowed server-side on min_timestamp over created_at) rather than
    # merging on a guessed composite key that could silently merge distinct actions.
    # include_details adds a `detail` object (carrying detail.conversation_id, the join
    # key to conversations) only when detail export is enabled for the team, so nothing
    # may depend on it being present.
    "agent_assist_actions": DecagonEndpointConfig(
        name="agent_assist_actions",
        path="/agent_assist/actions/export",
        data_key="events",
        primary_keys=None,
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        pagination="cursor",
        next_cursor_keys=("next_cursor",),
        has_more_key="has_more",
        partition_key="created_at",
        incremental_param="min_timestamp",
        incremental_param_format="epoch_seconds",
        extra_params={"include_details": "true"},
        # This export documents no ordering, so desc is the safe declaration (see the
        # field comment).
        sort_mode="desc",
        supports_append=True,
    ),
    # /article/all is the knowledge-base catalog Decagon's AI agent deflects with. It
    # pages on page/page_size over a `total` count and exposes no server-side timestamp
    # filter, so the table is full refresh only. `content` holds full article bodies,
    # which is why the batcher chunks are capped and the table ships opt-in until row
    # sizes are confirmed against a real knowledge base.
    "articles": DecagonEndpointConfig(
        name="articles",
        path="/article/all",
        data_key="articles",
        primary_keys=["id"],
        incremental_fields=[],
        pagination="page",
        page_size=100,
        total_key="total",
        partition_key="created_at",
        should_sync_default=False,
        chunk_size=500,
        chunk_size_bytes=50 * 1024 * 1024,
    ),
    # /article/usage returns per-article usage in one unpaginated response. The spec
    # elides the item schema behind {"usage": [...]}, so no primary key is claimed and
    # the table syncs as a full-refresh snapshot. The timezone is pinned to UTC so the
    # usage bucketing cannot silently shift with an account-level setting.
    "article_usage": DecagonEndpointConfig(
        name="article_usage",
        path="/article/usage",
        data_key="usage",
        primary_keys=None,
        incremental_fields=[],
        pagination="single",
        extra_params={"timezone": "UTC"},
    ),
    # /tag/all returns the whole tag taxonomy in one unpaginated response: the dimension
    # table that resolves the tag ids embedded in conversation rows to names, parents,
    # and hierarchy positions. get_counts populates human_count/total_count, point-in-time
    # aggregates that change on every sync. Tags carry no timestamp, so the table is
    # unpartitioned and full refresh only.
    "tags": DecagonEndpointConfig(
        name="tags",
        path="/tag/all",
        data_key="tags",
        primary_keys=["id"],
        incremental_fields=[],
        pagination="single",
        extra_params={"get_counts": "true"},
    ),
    # /admin_log/get is Decagon's audit trail of configuration changes: who changed what,
    # when, and the before/after state. Immutable rows paged on limit/offset over a
    # `total` count. Incremental sync filters server-side via `start`, preferred over
    # walking the offset history at 1 request/second. The spec types start/end loosely
    # rather than as the exports' epoch seconds, so the bound is sent as ISO 8601,
    # matching the ISO created_at column it filters; if that guess is wrong the sync
    # either fails loudly on a 4xx or degrades to a full walk, and the merge on id keeps
    # the table correct either way. Append is not offered for the same reason: with the
    # filter silently ignored, appends would re-add all history every sync.
    "admin_logs": DecagonEndpointConfig(
        name="admin_logs",
        path="/admin_log/get",
        data_key="admin_logs",
        primary_keys=["id"],
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        pagination="offset",
        page_size=100,
        total_key="total",
        partition_key="created_at",
        incremental_param="start",
        incremental_param_format="iso8601",
        # Unlike the exports, this endpoint 400s ("At least one of start or end dates is
        # required") on a bare request, so a full walk cannot omit the bound.
        incremental_param_required=True,
        # Ordering is undocumented for this endpoint; desc is the safe declaration (see
        # the field comment).
        sort_mode="desc",
        # Opt-in until what lands in details_before/details_after is confirmed against a
        # live account; config diffs can carry sensitive settings content.
        should_sync_default=False,
    ),
    # /team/api/members is the roster that resolves the user ids other Decagon tables
    # reference. One unpaginated request; members carry no timestamp, so the table is
    # unpartitioned and full refresh only. show_invite_status is requested so pending
    # invites land too (a complete roster); the `access` param is not sent in case it
    # filters rather than annotates. Rows are staff email addresses, so the table is a
    # deliberate opt-in.
    "team_members": DecagonEndpointConfig(
        name="team_members",
        path="/team/api/members",
        data_key="members",
        primary_keys=["id"],
        incremental_fields=[],
        pagination="single",
        extra_params={"show_invite_status": "true"},
        should_sync_default=False,
    ),
    # /watchtower/all lists Decagon's QA/evaluation jobs with their rubrics and
    # configuration, the context needed to interpret any quality scoring. One unpaginated
    # request, full refresh; rubric/prompt/outputs/config land as free-form JSON.
    "watchtower_jobs": DecagonEndpointConfig(
        name="watchtower_jobs",
        path="/watchtower/all",
        data_key="jobs",
        primary_keys=["id"],
        incremental_fields=[],
        pagination="single",
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(DECAGON_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DECAGON_ENDPOINTS.items()
}
