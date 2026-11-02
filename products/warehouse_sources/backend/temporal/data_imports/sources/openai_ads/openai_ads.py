import re
import json
import dataclasses
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, TypeVar

from dateutil import parser
from requests import HTTPError, Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sync_window import SyncWindow
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.openai_ads.settings import (
    INSIGHTS_PAGE_SIZE,
    LIST_PAGE_SIZE,
    OPENAI_ADS_BASE_URL,
    OPENAI_ADS_ENDPOINTS,
    OpenAIAdsEndpointConfig,
)

# Shared with the source's 401 and 403 entries in `get_non_retryable_errors` so a rejected key reads
# the same whether it surfaces while the source is being set up or during a later sync.
INVALID_CREDENTIALS_ERROR = (
    "Your OpenAI Ads API key is invalid or has been revoked. Create a new API key in the Settings "
    "tab of OpenAI Ads Manager, then reconnect."
)
NO_ACCESS_ERROR = (
    "Your OpenAI Ads API key does not have access to this ad account. Create a key for this ad "
    "account in the Settings tab of OpenAI Ads Manager, then reconnect."
)
UNREACHABLE_ERROR = (
    "Couldn't reach OpenAI Ads to validate your API key. This is usually temporary, so try again in a moment."
)
SERVER_ERROR_MESSAGE = (
    "OpenAI Ads had a temporary server error. This can also happen for a few minutes after you create an "
    "API key. The next sync will try again automatically."
)

# `requests` writes this prefix for every 403. The source's non-retryable 403 entry matches it.
_FORBIDDEN_PREFIX = "403 Client Error: Forbidden for url:"

_T = TypeVar("_T")

# OpenAI Ads keeps daily delivery reporting for the most recent 365 days and rejects an earlier
# `since` with a 400 (https://developers.openai.com/ads/reporting). The window is one day shorter
# because the API reads dates in the ad account's timezone and this source sends them in UTC.
INSIGHTS_HISTORY_DAYS = 364

# A first sync or full refresh asks for most of a year of daily buckets. OpenAI Ads can answer that
# request with a `server_error` on every run, while the few days an incremental run asks for read
# fine. So a long range is read in windows of at most this many days.
INSIGHTS_WINDOW_DAYS = 30


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


class OpenAIAdsServerError(Exception):
    """A 403 whose error body has the code `server_error`."""


def _retry_forbidden_server_errors(pages: Iterable[_T]) -> Iterator[_T]:
    """Re-raise a 403 with the body code `server_error` as a retryable error.

    OpenAI Ads sends this 403 for a server fault, and for a new API key for some minutes after
    it is created. The same key then works. The error text must not keep the `requests` 403
    prefix, because the source's non-retryable 403 entry matches it and disables the schema.
    """
    try:
        yield from pages
    except HTTPError as error:
        message = str(error)
        status = error.response.status_code if error.response is not None else None
        if status != 403 or "code=server_error" not in message:
            raise
        # Built from the message that is already redacted, not from the response URL.
        raise OpenAIAdsServerError(message.replace(_FORBIDDEN_PREFIX, "Server error (HTTP 403) for", 1)) from error


def _headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs
    # and raised errors; only the non-secret accept header is set here.
    return {"Accept": "application/json"}


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # One cheap probe against the campaigns list confirms the key is genuine. 200 => valid.
    # 403 => a real key the API recognizes but with restricted access; accept it at create time
    # (sync-time 403s are caught by get_non_retryable_errors). 401 => bad key.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{OPENAI_ADS_BASE_URL}/v1/campaigns?limit=1",
        headers={"Authorization": f"Bearer {api_key}", **_headers()},
        ok_statuses=(200, 403),
    )
    if ok:
        return True, None
    if status == 401:
        return False, INVALID_CREDENTIALS_ERROR
    # Anything else — a timeout, connection error, rate limit, or 5xx — says nothing about the key,
    # so point at retrying rather than sending the user off to replace a key that works.
    return False, UNREACHABLE_ERROR


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


def _insights_window(db_incremental_field_last_value: Optional[Any]) -> SyncWindow[str]:
    """The [since, until] ISO date window for one insights sync.

    Incremental runs start at the watermark (the pipeline already rewinds it by the configured
    lookback); full refreshes start at the oldest day the API still reports. A watermark older than
    that day is moved up to it too. `until` is yesterday: the API reads a `date_range` `until` as
    inclusive and moves it to the next midnight, and it rejects a bound in the future with a 400. So
    `until` set to today asks for a range that ends tomorrow, and every request fails. The trailing
    lookback re-reads the day once it is complete.
    """
    today = datetime.now(tz=UTC).date()
    until = today - timedelta(days=1)
    earliest = today - timedelta(days=INSIGHTS_HISTORY_DAYS)
    since = earliest
    if db_incremental_field_last_value is not None:
        since = max(_to_utc_date(db_incremental_field_last_value), earliest)
    since = min(since, until)
    return SyncWindow(start=since.isoformat(), end=until.isoformat())


def _split_insights_window(window: SyncWindow[str]) -> list[SyncWindow[str]]:
    start = date.fromisoformat(window.start)
    end = date.fromisoformat(window.end)
    windows: list[SyncWindow[str]] = []
    while True:
        last = min(start + timedelta(days=INSIGHTS_WINDOW_DAYS - 1), end)
        windows.append(SyncWindow(start=start.isoformat(), end=last.isoformat()))
        if last >= end:
            return windows
        start = last + timedelta(days=1)


def _convert_insights_times(row: dict[str, Any]) -> dict[str, Any]:
    # Bucket bounds arrive as epoch seconds; real timestamps are needed for the DateTime
    # incremental watermark and datetime partitioning.
    row = {**row}
    for key in ("start_time", "end_time"):
        value = row.get(key)
        if isinstance(value, int | float):
            row[key] = datetime.fromtimestamp(value, tz=UTC)
    return row


# The insights row id can carry a `plan=<compressed query plan>` segment next to the
# `start=`, `end=` and `entity_id=` segments. The plan value changes between requests for the same
# bucket, so the merge on `id` would insert every re-read lookback row as a new row.
_INSIGHTS_ID_PLAN_SEGMENT = re.compile(r"(?:^|:)plan=[^:]*")


def _stable_insights_id(row: dict[str, Any]) -> dict[str, Any]:
    row_id = row.get("id")
    if not isinstance(row_id, str):
        return row
    return {**row, "id": _INSIGHTS_ID_PLAN_SEGMENT.sub("", row_id).lstrip(":")}


def _make_client(api_key: str) -> RESTClient:
    return RESTClient(
        base_url=OPENAI_ADS_BASE_URL,
        headers=_headers(),
        auth=BearerTokenAuth(api_key),
    )


def _account_currency(api_key: str) -> str:
    for page in _retry_forbidden_server_errors(
        _make_client(api_key).paginate(path="/v1/ad_account", paginator=SinglePagePaginator(), data_selector="$")
    ):
        for account in page:
            currency = account.get("currency_code")
            if isinstance(currency, str) and re.fullmatch(r"[A-Z]{3}", currency):
                return currency
    raise ValueError("OpenAI Ads did not return an account currency. Check the account settings, then sync again.")


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
        return _source_response(config, lambda: _retry_forbidden_server_errors(_fan_out_rows(client, endpoint)))

    can_resume = resumable_source_manager.can_resume() and not config.single_object
    resume = resumable_source_manager.load_state() if can_resume else None

    if config.aggregation_level is not None:
        return _insights_source(
            config, api_key, team_id, job_id, resumable_source_manager, resume, db_incremental_field_last_value
        )

    if config.single_object:
        params: dict[str, Any] = {}
    else:
        # An explicit stable sort prevents page-boundary skips/duplicates while paginating the
        # full campaign list.
        params = {"limit": LIST_PAGE_SIZE, "order": "asc"}

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.cursor:
        initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; the checkpoint is saved AFTER a page is yielded,
        # pointing at the next page, so a crash resumes from a page whose predecessors were all
        # yielded — the overlap merge dedupes on the primary key.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(OpenAIAdsResumeConfig(cursor=state["cursor"]))

    resource = rest_api_resource(
        _rest_config(config, api_key, params, None),
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(
        config, lambda: _retry_forbidden_server_errors(resource), column_hints=resource.column_hints
    )


def _rest_config(
    config: OpenAIAdsEndpointConfig,
    api_key: str,
    params: dict[str, Any],
    data_map: Callable[[dict[str, Any]], dict[str, Any]] | None,
) -> RESTAPIConfig:
    return {
        "client": {
            "base_url": OPENAI_ADS_BASE_URL,
            "headers": _headers(),
            "auth": {"type": "bearer", "token": api_key},
        },
        "resource_defaults": None,
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "$" if config.single_object else "data",
                    "paginator": SinglePagePaginator() if config.single_object else _ListPaginator(),
                },
                "data_map": data_map,
            }
        ],
    }


def _insights_source(
    config: OpenAIAdsEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OpenAIAdsResumeConfig],
    resume: OpenAIAdsResumeConfig | None,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    full_window = _insights_window(db_incremental_field_last_value)
    if resume is not None and resume.since and resume.until:
        windows = [SyncWindow(start=resume.since, end=resume.until)]
        next_start = date.fromisoformat(resume.until) + timedelta(days=1)
        if next_start <= date.fromisoformat(full_window.end):
            windows += _split_insights_window(SyncWindow(start=next_start.isoformat(), end=full_window.end))
    else:
        windows = _split_insights_window(full_window)

    currency = _account_currency(api_key)

    def enrich_insights(row: dict[str, Any]) -> dict[str, Any]:
        return {**_convert_insights_times(_stable_insights_id(row)), "currency_code": currency}

    def window_resource(window: SyncWindow[str], cursor: str | None) -> Resource:
        params: dict[str, Any] = {
            "aggregation_level": config.aggregation_level,
            "time_granularity": "daily",
            "limit": INSIGHTS_PAGE_SIZE,
            # `requests` encodes the list as one repeated fields[] query param per element.
            "fields[]": list(config.insights_fields),
            # One JSON-encoded time-range object; the explicit timezone keeps daily buckets (and
            # therefore the bucket ids merge dedupes on) stable across runs.
            "time_ranges[]": json.dumps(
                {"type": "date_range", "since": window.start, "until": window.end, "timezone": "UTC"}
            ),
        }
        if config.segment is not None:
            params["segments[]"] = config.segment

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only while a next page remains; the checkpoint is saved AFTER a page is
            # yielded, pointing at the next page, so a crash resumes from a page whose predecessors
            # were all yielded — the overlap merge dedupes on the primary key. The window is pinned
            # with the cursor so the resumed cursor pairs with the result set it was issued for.
            if state and state.get("cursor"):
                resumable_source_manager.save_state(
                    OpenAIAdsResumeConfig(cursor=state["cursor"], since=window.start, until=window.end)
                )

        return rest_api_resource(
            _rest_config(config, api_key, params, enrich_insights),
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state={"cursor": cursor} if cursor else None,
        )

    first_resource = window_resource(windows[0], resume.cursor if resume is not None else None)

    def pages() -> Iterator[Any]:
        for index, window in enumerate(windows):
            resource = first_resource
            if index > 0:
                # Every row of the earlier windows is already yielded, so a resume can start here.
                resumable_source_manager.save_state(
                    OpenAIAdsResumeConfig(cursor=None, since=window.start, until=window.end)
                )
                resumable_source_manager.safe_point()
                resource = window_resource(window, None)
            # This wrapper hides the framework's own safe points, and a window can hold no rows.
            for page in resource:
                yield page
                resumable_source_manager.safe_point()

    return _source_response(
        config, lambda: _retry_forbidden_server_errors(pages()), column_hints=first_resource.column_hints
    )
