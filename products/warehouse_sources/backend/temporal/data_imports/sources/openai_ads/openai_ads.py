import json
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

from dateutil import parser
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.openai_ads.settings import (
    INSIGHTS_PAGE_SIZE,
    LIST_PAGE_SIZE,
    OPENAI_ADS_BASE_URL,
    OPENAI_ADS_ENDPOINTS,
    OpenAIAdsEndpointConfig,
)

# Floor for the insights window on a full refresh. OpenAI Ads launched to advertisers in 2026, so
# no reporting data can predate this; the whole window rides a single date_range request, so a
# generous floor costs nothing while staying within the API's 5-year time-range bound.
DEFAULT_INSIGHTS_SINCE = date(2025, 1, 1)


@dataclasses.dataclass
class OpenAIAdsResumeConfig:
    # `after` cursor for the page the sync should resume at. None means "start at the first page".
    cursor: str | None = None
    # Insights only: the date window (ISO dates) the saved cursor was issued for. A resumed sync
    # must reuse the exact window — recomputing "until" as a later day would pair the cursor with
    # a different result set.
    since: str | None = None
    until: str | None = None


class _ListPaginator(BasePaginator):
    """OpenAI-style list pagination: an `after` object-id cursor.

    `last_id` drives the next page, falling back to the last item's id so pagination keeps moving
    if `last_id` is ever absent. `has_more` is the authoritative stop signal — the API returns a
    `last_id` on the final page too, so a present token alone can't be trusted.
    """

    def __init__(self) -> None:
        super().__init__()
        self._after: Optional[str] = None

    def _apply(self, request: Request) -> None:
        if self._after is not None:
            if request.params is None:
                request.params = {}
            request.params["after"] = self._after

    def init_request(self, request: Request) -> None:
        # Apply a seeded resume cursor to the first request.
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            self._has_next_page = False
            return
        items = data or []
        last_id = body.get("last_id") or (items[-1].get("id") if items and isinstance(items[-1], dict) else None)
        if body.get("has_more") and last_id:
            self._after = last_id
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._after} if self._has_next_page and self._after is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._after = cursor
            self._has_next_page = True

    def __str__(self) -> str:
        return "_ListPaginator()"


def _headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs
    # and raised errors; only the non-secret accept header is set here.
    return {"Accept": "application/json"}


def validate_credentials(api_key: str) -> bool:
    # One cheap probe against the campaigns list confirms the key is genuine. 200 => valid.
    # 403 => a real key the API recognizes but with restricted access; accept it at create time
    # (sync-time 403s are caught by get_non_retryable_errors). 401 => bad key.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{OPENAI_ADS_BASE_URL}/v1/campaigns?limit=1",
        headers={"Authorization": f"Bearer {api_key}", **_headers()},
        ok_statuses=(200, 403),
    )
    return ok


def _to_utc_date(value: Any) -> date:
    """Coerce an incremental watermark (datetime/date/epoch/str) to a UTC calendar date."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC).date()
    return parser.parse(str(value)).astimezone(UTC).date()


def _insights_window(db_incremental_field_last_value: Optional[Any]) -> tuple[str, str]:
    """The [since, until] ISO date window for one insights sync.

    Incremental runs start at the watermark (the pipeline already rewinds it by the configured
    lookback); full refreshes start at the product-launch floor. `until` is today — the API
    rejects future dates.
    """
    until = datetime.now(tz=UTC).date()
    since = DEFAULT_INSIGHTS_SINCE
    if db_incremental_field_last_value is not None:
        since = _to_utc_date(db_incremental_field_last_value)
    since = min(since, until)
    return since.isoformat(), until.isoformat()


def _convert_insights_times(row: dict[str, Any]) -> dict[str, Any]:
    # Bucket bounds arrive as epoch seconds; real timestamps are needed for the DateTime
    # incremental watermark and datetime partitioning.
    row = {**row}
    for key in ("start_time", "end_time"):
        value = row.get(key)
        if isinstance(value, int | float):
            row[key] = datetime.fromtimestamp(value, tz=UTC)
    return row


def _make_client(api_key: str) -> RESTClient:
    return RESTClient(
        base_url=OPENAI_ADS_BASE_URL,
        headers=_headers(),
        auth=BearerTokenAuth(api_key),
    )


def _list_pages(client: RESTClient, path: str, params: dict[str, Any]) -> Iterator[list[dict[str, Any]]]:
    yield from client.paginate(
        path=path,
        params=params,
        paginator=_ListPaginator(),
        data_selector="data",
    )


def _fan_out_rows(client: RESTClient, endpoint: str) -> Iterator[list[dict[str, Any]]]:
    """Walk the campaign hierarchy for the fan-out entity streams.

    Ad groups list per campaign and ads list per ad group — both via required query params the
    declarative fan-out can't bind (it only resolves path placeholders). The response objects
    don't carry their parent ids, so every row is stamped with its lineage; the composite primary
    keys in settings.py rely on those stamped columns.
    """
    for campaign_page in _list_pages(client, "/v1/campaigns", {"limit": LIST_PAGE_SIZE, "order": "asc"}):
        for campaign in campaign_page:
            campaign_id = campaign.get("id")
            if campaign_id is None:
                continue
            for ad_group_page in _list_pages(
                client, "/v1/ad_groups", {"campaign_id": campaign_id, "limit": LIST_PAGE_SIZE, "order": "asc"}
            ):
                if endpoint == "ad_groups":
                    yield [{**row, "campaign_id": campaign_id} for row in ad_group_page]
                    continue
                for ad_group in ad_group_page:
                    ad_group_id = ad_group.get("id")
                    if ad_group_id is None:
                        continue
                    for ad_page in _list_pages(
                        client, "/v1/ads", {"ad_group_id": ad_group_id, "limit": LIST_PAGE_SIZE, "order": "asc"}
                    ):
                        yield [{**row, "campaign_id": campaign_id, "ad_group_id": ad_group_id} for row in ad_page]


def _source_response(config: OpenAIAdsEndpointConfig, items: Any, column_hints: Any = None) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=column_hints,
    )


def openai_ads_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OpenAIAdsResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = OPENAI_ADS_ENDPOINTS[endpoint]

    if endpoint in ("ad_groups", "ads"):
        # Multi-level fan-out with query-param parents: hand-rolled over the tracked, retrying
        # RESTClient. Not resumable — a retry re-walks the hierarchy and full refresh replaces.
        client = _make_client(api_key)
        return _source_response(config, lambda: _fan_out_rows(client, endpoint))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.aggregation_level is not None:
        if resume is not None and resume.since and resume.until:
            since, until = resume.since, resume.until
        else:
            since, until = _insights_window(db_incremental_field_last_value)
        params: dict[str, Any] = {
            "aggregation_level": config.aggregation_level,
            "time_granularity": "daily",
            "limit": INSIGHTS_PAGE_SIZE,
            # `requests` encodes the list as one repeated fields[] query param per element.
            "fields[]": list(config.insights_fields),
            # One JSON-encoded time-range object; the explicit timezone keeps daily buckets (and
            # therefore the bucket ids merge dedupes on) stable across runs.
            "time_ranges[]": json.dumps({"type": "date_range", "since": since, "until": until, "timezone": "UTC"}),
        }
        data_map = _convert_insights_times
    else:
        since = until = ""
        # An explicit stable sort prevents page-boundary skips/duplicates while paginating the
        # full campaign list.
        params = {"limit": LIST_PAGE_SIZE, "order": "asc"}
        data_map = None

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": OPENAI_ADS_BASE_URL,
            "headers": _headers(),
            "auth": {"type": "bearer", "token": api_key},
        },
        "resource_defaults": None,
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "data",
                    "paginator": _ListPaginator(),
                },
                "data_map": data_map,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.cursor:
        initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; the checkpoint is saved AFTER a page is yielded,
        # pointing at the next page, so a crash resumes from a page whose predecessors were all
        # yielded — the overlap merge dedupes on the primary key. Insights pin their window so the
        # resumed cursor pairs with the result set it was issued for.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(
                OpenAIAdsResumeConfig(cursor=state["cursor"], since=since or None, until=until or None)
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(config, lambda: resource, column_hints=resource.column_hints)
