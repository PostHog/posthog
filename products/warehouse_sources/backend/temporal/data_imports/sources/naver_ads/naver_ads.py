import hmac
import json
import time
import base64
import hashlib
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from requests import PreparedRequest, Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sync_window import SyncWindow
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.naverads import (
    NaverAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.naver_ads.settings import (
    ENDPOINTS,
    ENTITIES,
    MAX_HISTORY_DAYS,
    NAVER_ADS_BASE_URL,
    PAGE_SIZE,
    STAT_FIELDS,
    STATS_IDS_PER_REQUEST,
    STATS_TIMEZONE,
    EntityKind,
    NaverAdsEndpoint,
)

Rows = list[dict[str, Any]]


@frozen
class NaverAdsResumeConfig:
    # Entity tables: the last parent id whose children are written. Stats tables: the last entity id
    # written for `stat_date`.
    after_id: str | None = None
    stat_date: str | None = None
    # The stats window is pinned so a resumed attempt reads the same days.
    window_start: str | None = None
    window_end: str | None = None


class NaverAdsAuth(AuthConfigBase):
    """Signs each request with HMAC-SHA256 over `{timestamp}.{METHOD}.{path}`, as the Search Ad API requires."""

    def __init__(self, api_key: str, secret_key: str, customer_id: str) -> None:
        self.api_key = api_key
        self.secret_key = secret_key
        self.customer_id = customer_id

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        timestamp = str(int(time.time() * 1000))
        path = urlsplit(request.url or "").path
        message = f"{timestamp}.{request.method}.{path}"
        digest = hmac.new(self.secret_key.encode(), message.encode(), hashlib.sha256).digest()
        request.headers["X-Timestamp"] = timestamp
        request.headers["X-API-KEY"] = self.api_key
        request.headers["X-Customer"] = self.customer_id
        request.headers["X-Signature"] = base64.b64encode(digest).decode()
        return request

    def secret_values(self) -> tuple[str, ...]:
        return tuple(value for value in (self.secret_key, self.api_key) if value)


class NaverAdsKeysetPaginator(BasePaginator):
    """Pages a list with `recordSize` and `baseSearchId`, the id of the last row already read."""

    def __init__(self, id_field: str, page_size: int) -> None:
        super().__init__()
        self.id_field = id_field
        self.page_size = page_size
        self.base_id: str | None = None

    def init_request(self, request: Request) -> None:
        self.update_request(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        rows = data or []
        if len(rows) < self.page_size:
            self._has_next_page = False
            return
        last_id = rows[-1].get(self.id_field) if isinstance(rows[-1], dict) else None
        if not last_id or last_id == self.base_id:
            raise ValueError(f"Naver Ads pagination did not advance past {self.base_id!r}")
        self.base_id = str(last_id)

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["recordSize"] = self.page_size
        if self.base_id is not None:
            request.params["baseSearchId"] = self.base_id


def make_client(config: NaverAdsSourceConfig) -> RESTClient:
    return RESTClient(
        base_url=NAVER_ADS_BASE_URL,
        auth=NaverAdsAuth(config.api_key, config.secret_key, config.customer_id.strip()),
        allowed_hosts=[],
        allow_redirects=False,
    )


def list_entities(client: RESTClient, kind: EntityKind, parent_id: str | None = None) -> Iterator[Rows]:
    """Yield each page of an entity list, one page per request."""
    entity = ENTITIES[kind]
    params: dict[str, Any] = {}
    if entity.parent_param is not None and parent_id is not None:
        params[entity.parent_param] = parent_id
    paginator: BasePaginator = (
        NaverAdsKeysetPaginator(entity.id_field, PAGE_SIZE) if entity.keyset_paginated else SinglePagePaginator()
    )
    previous_last_id: Any = None
    for page in client.paginate(
        path=entity.path, params=params, paginator=paginator, data_selector=None, data_selector_required=True
    ):
        # Naver does not document whether `baseSearchId` is inclusive, so drop the row it names if it comes back.
        rows = [row for row in page if previous_last_id is None or row.get(entity.id_field) != previous_last_id]
        if page:
            previous_last_id = page[-1].get(entity.id_field)
        yield rows


def entity_ids(client: RESTClient, kind: EntityKind, safe_point: Callable[[], None]) -> list[str]:
    """Every id of one entity kind in the account, sorted so a resumed run walks them in the same order."""
    entity = ENTITIES[kind]
    parent_ids = entity_ids(client, entity.parent, safe_point) if entity.parent is not None else [None]
    ids: list[str] = []
    for parent_id in parent_ids:
        for page in list_entities(client, kind, parent_id):
            ids.extend(str(row[entity.id_field]) for row in page if row.get(entity.id_field))
            safe_point()
    return sorted(set(ids))


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def stats_window(
    endpoint: NaverAdsEndpoint,
    inputs: SourceInputs,
    resume: NaverAdsResumeConfig | None,
    today: date,
) -> SyncWindow[date]:
    if resume is not None and resume.window_start and resume.window_end:
        return SyncWindow(start=date.fromisoformat(resume.window_start), end=date.fromisoformat(resume.window_end))

    earliest = today - timedelta(days=MAX_HISTORY_DAYS)
    watermark = _to_date(inputs.db_incremental_field_last_value) if inputs.should_use_incremental_field else None
    if watermark is not None:
        start = watermark
    elif inputs.history_start is not None:
        start = inputs.history_start.astimezone(ZoneInfo(STATS_TIMEZONE)).date()
    else:
        start = today - timedelta(days=endpoint.history_days or MAX_HISTORY_DAYS)
    return SyncWindow(start=min(max(start, earliest), today), end=today)


def fetch_stats(client: RESTClient, ids: list[str], day: date) -> Rows:
    params = {
        "ids": ",".join(ids),
        "fields": json.dumps(list(STAT_FIELDS)),
        "timeRange": json.dumps({"since": day.isoformat(), "until": day.isoformat()}),
    }
    rows: Rows = []
    for page in client.paginate(
        path="/stats",
        params=params,
        paginator=SinglePagePaginator(),
        data_selector="data",
        data_selector_required=True,
    ):
        # Zero-metric rows are kept: a restated day can drop to zero, and the watermark advances only on rows written.
        rows.extend({**row, "date": day} for row in page if isinstance(row, dict) and row.get("id"))
    return rows


def stats_rows(
    client: RESTClient,
    endpoint: NaverAdsEndpoint,
    inputs: SourceInputs,
    manager: ResumableSourceManager[NaverAdsResumeConfig],
    today: date,
) -> Iterator[Rows]:
    """One `/stats` summary per day and chunk of ids, oldest day first.

    Bulk `ids` requests return per-entity totals for the range, not daily rows, so each day is a separate request.
    """
    resume = manager.load_state() if manager.can_resume() else None
    window = stats_window(endpoint, inputs, resume, today)
    start, end = window.start, window.end
    resume_day = date.fromisoformat(resume.stat_date) if resume is not None and resume.stat_date else None
    resume_after = resume.after_id if resume is not None else None

    ids = entity_ids(client, endpoint.entity, manager.safe_point)

    day = max(start, resume_day) if resume_day is not None else start
    while day <= end and ids:
        # Ids are compared one by one, because an entity removed since the last attempt shifts chunk boundaries.
        day_ids = [i for i in ids if i > resume_after] if day == resume_day and resume_after is not None else ids
        chunks = [day_ids[i : i + STATS_IDS_PER_REQUEST] for i in range(0, len(day_ids), STATS_IDS_PER_REQUEST)]
        for index, chunk in enumerate(chunks):
            rows = fetch_stats(client, chunk, day)
            last_of_day = index == len(chunks) - 1
            manager.save_state(
                NaverAdsResumeConfig(
                    after_id=None if last_of_day else chunk[-1],
                    stat_date=(day + timedelta(days=1)).isoformat() if last_of_day else day.isoformat(),
                    window_start=start.isoformat(),
                    window_end=end.isoformat(),
                )
            )
            if rows:
                yield rows
            else:
                manager.safe_point()
        day += timedelta(days=1)


def entity_rows(
    client: RESTClient,
    endpoint: NaverAdsEndpoint,
    manager: ResumableSourceManager[NaverAdsResumeConfig],
) -> Iterator[Rows]:
    entity = ENTITIES[endpoint.entity]
    if entity.parent is None:
        for page in list_entities(client, endpoint.entity):
            if page:
                yield page
            else:
                manager.safe_point()
        return

    resume = manager.load_state() if manager.can_resume() else None
    resume_after = resume.after_id if resume is not None else None
    for parent_id in entity_ids(client, entity.parent, manager.safe_point):
        if resume_after is not None and parent_id <= resume_after:
            continue
        # A parent's rows are held until its last page, so the saved parent id never covers a partial parent.
        rows: Rows = []
        for page in list_entities(client, endpoint.entity, parent_id):
            rows.extend(page)
        manager.save_state(NaverAdsResumeConfig(after_id=parent_id))
        if rows:
            yield rows
        else:
            manager.safe_point()


def naver_ads_source(
    config: NaverAdsSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[NaverAdsResumeConfig],
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    client = make_client(config)

    if endpoint.is_stats:
        today = datetime.now(UTC).astimezone(ZoneInfo(STATS_TIMEZONE)).date()
        return SourceResponse(
            name=endpoint.name,
            items=lambda: stats_rows(client, endpoint, inputs, manager, today),
            primary_keys=list(endpoint.primary_keys),
            partition_mode="datetime",
            partition_format="month",
            partition_keys=["date"],
            sort_mode="asc",
            on_complete=manager.clear_state,
        )

    return SourceResponse(
        name=endpoint.name,
        items=lambda: entity_rows(client, endpoint, manager),
        primary_keys=list(endpoint.primary_keys),
        on_complete=manager.clear_state,
    )


def validate_credentials(config: NaverAdsSourceConfig) -> tuple[bool, str | None]:
    auth = NaverAdsAuth(config.api_key, config.secret_key, config.customer_id.strip())
    session = make_tracked_session(redact_values=auth.secret_values(), allow_redirects=False)
    try:
        response = session.get(
            f"{NAVER_ADS_BASE_URL}/ncc/campaigns",
            params={"recordSize": 1},
            auth=auth,
            timeout=30,
        )
    except Exception:
        return False, "Could not reach the Naver Search Ad API. Try again in a few minutes."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return (
            False,
            "Naver rejected these credentials. Check the API license, secret key and customer ID "
            "in Search Ad Manager under Tools > API Manager.",
        )
    return False, f"Naver returned status {response.status_code} when checking these credentials."
