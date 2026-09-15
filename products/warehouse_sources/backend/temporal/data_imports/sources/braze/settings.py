from dataclasses import dataclass, field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Braze list endpoints paginate either with a 0-indexed ``page`` param
# (campaigns/canvas/segments/events) or a ``limit``/``offset`` pair
# (templates/content blocks). The cursor we persist for resume is the raw page
# index or row offset respectively.
PaginationStyle = Literal["page", "offset"]


@dataclass
class BrazeEndpointConfig:
    name: str
    path: str
    # Key in the JSON response body holding the list of rows.
    data_key: str
    primary_key: str
    pagination: PaginationStyle
    page_size: int = 100
    # Stable (immutable) datetime field used for partitioning. Only set when the
    # response actually carries a creation timestamp — never an updated/last-edit
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Server-side "modified since" query param. Set only for endpoints where Braze
    # genuinely filters by it (templates/email, content_blocks). When None the
    # endpoint is full-refresh only.
    modified_after_param: Optional[str] = None
    # events/list returns a bare list of event-name strings rather than objects;
    # wrap each string under this key so the row is a dict with a stable primary key.
    wrap_scalar_as: Optional[str] = None


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


BRAZE_ENDPOINTS: dict[str, BrazeEndpointConfig] = {
    "campaigns": BrazeEndpointConfig(
        name="campaigns",
        path="/campaigns/list",
        data_key="campaigns",
        primary_key="id",
        pagination="page",
        # /campaigns/list documents a `last_edit.time[gte]` filter, but its bracketed
        # param syntax is fragile and we couldn't curl-verify it filters server-side
        # (no API key available), so we ship full refresh. last_edit is also mutable,
        # so it can't serve as a partition key.
    ),
    "canvases": BrazeEndpointConfig(
        name="canvases",
        path="/canvas/list",
        data_key="canvases",
        primary_key="id",
        pagination="page",
        # See campaigns: a documented but unverified `last_edit.time[gte]` filter exists.
    ),
    "segments": BrazeEndpointConfig(
        name="segments",
        path="/segments/list",
        data_key="segments",
        primary_key="id",
        pagination="page",
    ),
    "events": BrazeEndpointConfig(
        name="events",
        path="/events/list",
        data_key="events",
        primary_key="event_name",
        pagination="page",
        page_size=250,
        wrap_scalar_as="event_name",
    ),
    "email_templates": BrazeEndpointConfig(
        name="email_templates",
        path="/templates/email/list",
        data_key="templates",
        primary_key="email_template_id",
        pagination="offset",
        partition_key="created_at",
        incremental_fields=[_datetime_field("updated_at")],
        modified_after_param="modified_after",
    ),
    "content_blocks": BrazeEndpointConfig(
        name="content_blocks",
        path="/content_blocks/list",
        data_key="content_blocks",
        primary_key="content_block_id",
        pagination="offset",
        partition_key="created_at",
        # The mutable field on a content block is `last_edited`; offer it as the
        # incremental cursor since the server-side `modified_after` filter keys off it.
        incremental_fields=[_datetime_field("last_edited")],
        modified_after_param="modified_after",
    ),
}

# Braze's analytics endpoints (`/*/data_series`) return a daily series instead of a page of
# rows. Each takes a window — `ending_at` plus a `length` in days capped per endpoint — and the
# campaign/canvas/event series also need an id from the matching list endpoint, so those fan out
# one request per parent row.
DataSeriesShape = Literal["list", "canvas"]

# How far back a first sync (or a full refresh) of a data series reaches. Braze caps `length` at
# 100 days, so a longer span would only mean more requests per parent for older history.
DATA_SERIES_HISTORY_DAYS = 100

# Braze restates recent days as conversions attribute back to the send date, so incremental runs
# re-read a trailing window rather than resuming at the last day already stored.
DATA_SERIES_LOOKBACK_SECONDS = 14 * 24 * 60 * 60


def _date_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.Date,
        "field": name,
        "field_type": IncrementalFieldType.Date,
    }


DATA_SERIES_INCREMENTAL_FIELDS: list[IncrementalField] = [_date_field("time")]


@frozen
class BrazeDataSeriesConfig:
    name: str
    path: str
    primary_keys: list[str]
    # Braze's documented maximum for this endpoint's `length` param, in days.
    max_length_days: int
    # The list endpoint supplying the required id, the row field holding it, the query param it
    # goes in, and the column it lands in. All None for the workspace-level KPI series.
    parent: Optional[str] = None
    parent_id_field: Optional[str] = None
    parent_id_param: Optional[str] = None
    parent_id_column: Optional[str] = None
    # Parent row field that must be truthy for the parent to have a series at all. Braze only
    # keeps a size history for segments with analytics tracking switched on, and asking for an
    # untracked one errors, which would abort the whole fan-out.
    parent_filter_field: Optional[str] = None
    # /canvas/data_series nests its series under `data.stats`; every other series returns `data`
    # as a flat list.
    shape: DataSeriesShape = "list"
    params: dict[str, str] = field(default_factory=dict)
    # Response fields whose keys vary per row — the per-channel `messages` map, the variant and
    # step maps keyed by API identifier. JSON-encoded so the column keeps one type across rows.
    json_fields: tuple[str, ...] = ()
    # `time` is the day the row describes, so it never moves once written.
    partition_key: Optional[str] = None


BRAZE_DATA_SERIES_ENDPOINTS: dict[str, BrazeDataSeriesConfig] = {
    "campaign_analytics": BrazeDataSeriesConfig(
        name="campaign_analytics",
        path="/campaigns/data_series",
        primary_keys=["campaign_id", "time"],
        max_length_days=100,
        parent="campaigns",
        parent_id_field="id",
        parent_id_param="campaign_id",
        parent_id_column="campaign_id",
        json_fields=("messages",),
        partition_key="time",
    ),
    "canvas_analytics": BrazeDataSeriesConfig(
        name="canvas_analytics",
        path="/canvas/data_series",
        primary_keys=["canvas_id", "time"],
        max_length_days=14,
        parent="canvases",
        parent_id_field="id",
        parent_id_param="canvas_id",
        parent_id_column="canvas_id",
        shape="canvas",
        params={"include_variant_breakdown": "true", "include_step_breakdown": "true"},
        json_fields=("variant_stats", "step_stats"),
        partition_key="time",
    ),
    "event_analytics": BrazeDataSeriesConfig(
        name="event_analytics",
        path="/events/data_series",
        primary_keys=["event_name", "time"],
        max_length_days=100,
        parent="events",
        parent_id_field="event_name",
        parent_id_param="event",
        parent_id_column="event_name",
        partition_key="time",
    ),
    "segment_analytics": BrazeDataSeriesConfig(
        name="segment_analytics",
        path="/segments/data_series",
        primary_keys=["segment_id", "time"],
        max_length_days=100,
        parent="segments",
        parent_id_field="id",
        parent_id_param="segment_id",
        parent_id_column="segment_id",
        parent_filter_field="analytics_tracking_enabled",
        partition_key="time",
    ),
    "kpi_dau": BrazeDataSeriesConfig(
        name="kpi_dau",
        path="/kpi/dau/data_series",
        primary_keys=["time"],
        max_length_days=100,
    ),
    "kpi_mau": BrazeDataSeriesConfig(
        name="kpi_mau",
        path="/kpi/mau/data_series",
        primary_keys=["time"],
        max_length_days=100,
    ),
    "kpi_new_users": BrazeDataSeriesConfig(
        name="kpi_new_users",
        path="/kpi/new_users/data_series",
        primary_keys=["time"],
        max_length_days=100,
    ),
    "kpi_uninstalls": BrazeDataSeriesConfig(
        name="kpi_uninstalls",
        path="/kpi/uninstalls/data_series",
        primary_keys=["time"],
        max_length_days=100,
    ),
}


# Braze's `details` endpoints return one object describing a single campaign or Canvas — the
# variants, steps, channels and conversion behaviors the matching list endpoint leaves out. Each
# takes only the parent id, so they fan out one request per row of that list endpoint.
@frozen
class BrazeDetailsConfig:
    name: str
    path: str
    # The list endpoint supplying the required id, the row field holding it, the query param it
    # goes in, and the column it lands in.
    parent: str
    parent_id_field: str
    parent_id_param: str
    parent_id_column: str
    # Response fields whose keys or member shapes vary per row — the variation map keyed by API
    # identifier, and the step/variant/behavior lists. JSON-encoded so the column keeps one type.
    json_fields: tuple[str, ...] = ()
    # `created_at` never moves once the campaign or Canvas exists.
    partition_key: Optional[str] = None


BRAZE_DETAILS_ENDPOINTS: dict[str, BrazeDetailsConfig] = {
    "campaign_details": BrazeDetailsConfig(
        name="campaign_details",
        path="/campaigns/details",
        parent="campaigns",
        parent_id_field="id",
        parent_id_param="campaign_id",
        parent_id_column="campaign_id",
        json_fields=("messages", "conversion_behaviors"),
        partition_key="created_at",
    ),
    "canvas_details": BrazeDetailsConfig(
        name="canvas_details",
        path="/canvas/details",
        parent="canvases",
        parent_id_field="id",
        parent_id_param="canvas_id",
        parent_id_column="canvas_id",
        json_fields=("variants", "steps"),
        partition_key="created_at",
    ),
}


def _probe_target(config: BrazeDataSeriesConfig) -> str:
    # A data series rejects a request missing its required params, so probe with enough of one to
    # get a 200/401/403 back. The fan-out series need a parent id we don't have before syncing,
    # so they probe the list endpoint their fan-out walks — a permission the sync needs anyway.
    if config.parent is not None:
        return f"{BRAZE_ENDPOINTS[config.parent].path}?page=0"
    return f"{config.path}?length=1"


# Request each endpoint's credential probe sends, path and query.
BRAZE_PROBE_TARGETS: dict[str, str] = {
    **{name: f"{config.path}?page=0" for name, config in BRAZE_ENDPOINTS.items()},
    **{name: _probe_target(config) for name, config in BRAZE_DATA_SERIES_ENDPOINTS.items()},
    # A details endpoint rejects a request without its parent id, so it probes the list endpoint
    # its fan-out walks — same reasoning as the fan-out series above.
    **{name: f"{BRAZE_ENDPOINTS[config.parent].path}?page=0" for name, config in BRAZE_DETAILS_ENDPOINTS.items()},
}

DEFAULT_PROBE_TARGET = BRAZE_PROBE_TARGETS["campaigns"]

ENDPOINTS = (
    tuple(BRAZE_ENDPOINTS.keys()) + tuple(BRAZE_DATA_SERIES_ENDPOINTS.keys()) + tuple(BRAZE_DETAILS_ENDPOINTS.keys())
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    **{name: config.incremental_fields for name, config in BRAZE_ENDPOINTS.items()},
    **dict.fromkeys(BRAZE_DATA_SERIES_ENDPOINTS, DATA_SERIES_INCREMENTAL_FIELDS),
    # A details endpoint takes only the parent id — no server-side time filter, so full refresh.
    **dict.fromkeys(BRAZE_DETAILS_ENDPOINTS, []),
}
