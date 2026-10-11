from dataclasses import field
from typing import Optional

from sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType, SortMode, frozen


@frozen
class LemlistEndpointConfig:
    name: str
    path: str
    # offset/limit pagination. Some lemlist endpoints (team, team/senders) return the full
    # result in a single response and expose no offset param, so they're fetched in one request.
    paginate: bool = True
    # lemlist's newer response shapes require `version=v2` on a couple of list endpoints.
    requires_version_v2: bool = False
    # `version=v2` is optional here but enriches the response (e.g. /team gains a `users` array), so
    # it's sent only when the source is pinned to v2 — v1 pins keep the leaner shape byte-for-byte.
    version_v2_enriches: bool = False
    # `/team` returns a single object rather than an array; wrap it into a one-row table.
    single_object: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["_id"])
    partition_key: Optional[str] = None  # stable creation-time field for datetime partitioning
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Server-side time filter param (minDate) is honoured only on /activities, so it's the one
    # endpoint that can sync incrementally. Everything else is full refresh.
    supports_incremental: bool = False
    # /activities returns newest-first and exposes no sort param, so its watermark must be
    # finalised at end-of-run (sort_mode="desc"); the paginated full-refresh endpoints request
    # createdAt ascending for stable page boundaries.
    sort_mode: SortMode = "asc"
    request_sort_by: Optional[str] = None
    request_sort_order: Optional[str] = None
    # Bound the first incremental sync so we don't pull the entire activity history at once.
    default_lookback_days: Optional[int] = None
    should_sync_default: bool = True
    # JSONPath to the row list when the response wraps it (e.g. /contacts returns {"data": [...]}).
    data_selector: Optional[str] = None
    # Per-campaign child endpoints fan out over /campaigns; their rows carry the parent id.
    fanout: Optional[DependentEndpointConfig] = None
    # Read by the shared fan-out helper; lemlist list pages hold at most 100 rows.
    page_size: int = 100
    default_incremental_field: Optional[str] = None


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


def _campaign_fanout(
    include_campaign_id: bool, child_params: Optional[dict[str, str]] = None
) -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name="campaigns",
        resolve_param="campaignId",
        resolve_field="_id",
        include_from_parent=["_id"] if include_campaign_id else [],
        parent_field_renames={"_id": "campaignId"} if include_campaign_id else {},
        child_params=child_params or {},
        # A campaign deleted between the listing and the child fetch 404s; skip it rather than
        # failing the sync with the "no user for this API key" 404 message.
        child_response_actions=[{"status_code": 404, "action": "ignore"}],
    )


LEMLIST_ENDPOINTS: dict[str, LemlistEndpointConfig] = {
    "campaigns": LemlistEndpointConfig(
        name="campaigns",
        path="/campaigns",
        requires_version_v2=True,
        partition_key="createdAt",
        request_sort_by="createdAt",
        request_sort_order="asc",
    ),
    "activities": LemlistEndpointConfig(
        name="activities",
        path="/activities",
        requires_version_v2=True,
        partition_key="createdAt",
        supports_incremental=True,
        incremental_fields=[_datetime_incremental_field("createdAt")],
        sort_mode="desc",
        default_lookback_days=365,
    ),
    "team": LemlistEndpointConfig(
        name="team",
        path="/team",
        paginate=False,
        single_object=True,
        partition_key="createdAt",
        version_v2_enriches=True,
    ),
    "team_senders": LemlistEndpointConfig(
        name="team_senders",
        path="/team/senders",
        paginate=False,
        primary_keys=["userId"],
    ),
    # lemlist marks Get Many Unsubscribes as legacy/deprecated, but it's the only documented list
    # endpoint that returns a flat array with a stable `_id`, so it's the practical choice for a
    # full-refresh table. Partitioning is left off because the docs disagree on the timestamp field
    # name (createdAt vs unsubscribedAt) — see canonical_descriptions for the documented shape.
    "unsubscribes": LemlistEndpointConfig(
        name="unsubscribes",
        path="/unsubscribes",
    ),
    # Without a filter /contacts lists every contact in a {data, total, limit, offset} envelope. It
    # exposes no sort or date filter, so it's full refresh only.
    "contacts": LemlistEndpointConfig(
        name="contacts",
        path="/contacts",
        data_selector="data",
        partition_key="createdAt",
    ),
    # GET /campaigns/{id}/leads/ caps a response at 500 leads with no offset param, so the JSON
    # export is the only way to read every lead of a campaign. Lead ids are scoped to their
    # campaign, so the key carries the campaign id.
    "campaign_leads": LemlistEndpointConfig(
        name="campaign_leads",
        path="/v2/campaigns/{campaignId}/export/leads",
        paginate=False,
        primary_keys=["campaignId", "_id"],
        fanout=_campaign_fanout(include_campaign_id=True, child_params={"state": "all", "format": "json"}),
    ),
    # All-time headline stats per campaign; each report row's `_id` is the campaign id.
    "campaign_reports": LemlistEndpointConfig(
        name="campaign_reports",
        path="/campaigns/reports?campaignIds={campaignId}",
        paginate=False,
        partition_key="createdAt",
        fanout=_campaign_fanout(include_campaign_id=False),
    ),
    # The response is an object keyed by sequence id (condition branches are their own sequences),
    # so `$.*` turns its values into one row per sequence, each with its ordered `steps`.
    "campaign_sequences": LemlistEndpointConfig(
        name="campaign_sequences",
        path="/campaigns/{campaignId}/sequences",
        paginate=False,
        data_selector="$.*",
        primary_keys=["campaignId", "_id"],
        fanout=_campaign_fanout(include_campaign_id=True),
    ),
}

ENDPOINTS = tuple(LEMLIST_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LEMLIST_ENDPOINTS.items()
}
