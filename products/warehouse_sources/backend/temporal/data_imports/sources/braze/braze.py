import re
import json
import dataclasses
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.braze.settings import (
    BRAZE_DATA_SERIES_ENDPOINTS,
    BRAZE_ENDPOINTS,
    DATA_SERIES_HISTORY_DAYS,
    DEFAULT_PROBE_TARGET,
    BrazeDataSeriesConfig,
    BrazeEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Resource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# Shared so the source-layer 403 acceptance check can't drift from the message produced here.
BRAZE_FORBIDDEN_MSG = "Your Braze API key does not have permission for this endpoint"
HOST_NOT_ALLOWED_ERROR = "Braze REST endpoint URL is not allowed"


class BrazeHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class BrazeResumeConfig:
    # Page index (page pagination) or row offset (offset pagination) to resume from.
    # Old checkpoints stored the last-yielded cursor, so re-loading one re-fetches that
    # page and merge dedupes on primary key.
    cursor: int


def normalize_base_url(url: str) -> str:
    """Force https and strip any trailing slash so endpoint paths join cleanly.

    Forcing https prevents a downgrade to plaintext, matching the Okta/ServiceNow
    connectors that also take a user-supplied host.
    """
    url = re.sub(r"^https?://", "", url.strip(), flags=re.IGNORECASE)
    return f"https://{url.rstrip('/')}"


def _host_from_url(base_url: str) -> str:
    return (urlparse(normalize_base_url(base_url)).hostname or "").lower()


def _format_modified_after(value: Any) -> str:
    """Format an incremental cursor value as an ISO-8601 string for Braze filters."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _normalize_items(config: BrazeEndpointConfig, items: list[Any]) -> list[dict[str, Any]]:
    if config.wrap_scalar_as:
        return [{config.wrap_scalar_as: item} for item in items]
    return [item for item in items if isinstance(item, dict)]


class BrazeOffsetPaginator(BasePaginator):
    """Braze's limit/offset pagination (templates/content blocks).

    Diverges from the generic ``OffsetPaginator`` in two Braze-specific ways: the
    ``offset`` param must be omitted when 0 (Braze rejects ``offset=0`` as not a
    positive integer), and only an empty page terminates — a short page is not
    treated as the last one.
    """

    def __init__(self, limit: int, offset: int = 0) -> None:
        super().__init__()
        self.limit = limit
        self.offset = offset

    def _inject_params(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["limit"] = self.limit
        if self.offset:
            request.params["offset"] = self.offset

    def init_request(self, request: Request) -> None:
        self._inject_params(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        self.offset += self.limit
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._inject_params(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.offset already points at the next page to fetch (update_state incremented it).
        return {"offset": self.offset} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self.offset = int(offset)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"BrazeOffsetPaginator(offset={self.offset}, limit={self.limit})"


def validate_credentials(
    api_key: str, base_url: str, probe_target: str = DEFAULT_PROBE_TARGET, team_id: int | None = None
) -> tuple[bool, str | None]:
    """Probe a Braze endpoint to confirm the REST API key is valid.

    Braze keys are scoped per endpoint, so a 403 means the key is genuine but
    lacks the probed scope — the caller decides whether to accept that.
    """
    # The REST endpoint URL is fully customer-controlled, so block hosts that resolve to
    # private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(_host_from_url(base_url), team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = f"{normalize_base_url(base_url)}{probe_target}"
    ok, status = validate_via_probe(
        # No redirects: keep the probe pinned to the validated host (SSRF hardening).
        lambda: make_tracked_session(allow_redirects=False, redact_values=(api_key,)),
        url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Braze API key"
    if status == 403:
        return False, BRAZE_FORBIDDEN_MSG
    if status is None:
        return False, "Could not reach the Braze API"
    return False, f"Braze API returned status {status}"


def _paginator_for(config: BrazeEndpointConfig) -> tuple[BasePaginator, str]:
    if config.pagination == "page":
        return PageNumberPaginator(base_page=0), "page"
    return BrazeOffsetPaginator(limit=config.page_size), "offset"


def _list_resource(
    api_key: str,
    base_url: str,
    config: BrazeEndpointConfig,
    team_id: int,
    job_id: str,
    paginator: BasePaginator,
    params: Optional[dict[str, Any]] = None,
    db_incremental_field_last_value: Optional[Any] = None,
    resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None,
    initial_paginator_state: Optional[dict[str, Any]] = None,
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": normalize_base_url(base_url),
            "headers": {"Accept": "application/json"},
            # Framework Bearer auth so the key is redacted from logs.
            "auth": {"type": "bearer", "token": api_key},
            # No redirects: the base URL is customer-supplied, so keep traffic pinned
            # to the validated host (SSRF hardening).
            "session": make_tracked_session(allow_redirects=False, redact_values=(api_key,)),
            "paginator": paginator,
        },
        "resource_defaults": None,
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": params or {},
                    # Braze omits the data key when there is nothing to return, so a missing
                    # key is a normal end-of-data page — don't set data_selector_required.
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )


def _to_date(value: Any) -> Optional[date]:
    parsed = parse_datetime_value(value)
    return parsed.date() if parsed is not None else None


def _series_span_days(
    should_use_incremental_field: bool, db_incremental_field_last_value: Optional[Any], today: date
) -> int:
    """Days of history a run asks for, measured back from today."""
    watermark = _to_date(db_incremental_field_last_value) if should_use_incremental_field else None
    if watermark is None:
        return DATA_SERIES_HISTORY_DAYS
    # The watermark day is re-read rather than skipped: Braze can still be restating it.
    return max(1, min((today - watermark).days + 1, DATA_SERIES_HISTORY_DAYS))


def _series_windows(max_length_days: int, span_days: int, now: datetime) -> list[tuple[datetime, int]]:
    """Split a span into (ending_at, length) windows Braze accepts, oldest first.

    Braze caps `length` per endpoint — 14 days on Canvas, 100 elsewhere — so a longer span is
    covered by stepping `ending_at` back one whole window at a time.
    """
    windows: list[tuple[datetime, int]] = []
    ending = now
    remaining = span_days
    while remaining > 0:
        length = min(remaining, max_length_days)
        windows.append((ending, length))
        remaining -= length
        ending -= timedelta(days=length)
    return list(reversed(windows))


def _encode_json_fields(row: dict[str, Any], json_fields: tuple[str, ...]) -> dict[str, Any]:
    for name in json_fields:
        row[name] = json.dumps(row.get(name) or {})
    return row


def _canvas_series_rows(config: BrazeDataSeriesConfig, canvas_id: Optional[str], data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    rows: list[dict[str, Any]] = []
    for point in data.get("stats") or []:
        if not isinstance(point, dict):
            continue
        total_stats = point.get("total_stats")
        row: dict[str, Any] = {
            "canvas_id": canvas_id,
            "canvas_name": data.get("name"),
            "time": point.get("time"),
            **(total_stats if isinstance(total_stats, dict) else {}),
            "variant_stats": point.get("variant_stats"),
            "step_stats": point.get("step_stats"),
        }
        rows.append(_encode_json_fields(row, config.json_fields))
    return rows


def _series_rows(config: BrazeDataSeriesConfig, parent_id: Optional[str], body: Any) -> list[dict[str, Any]]:
    data = body.get("data") if isinstance(body, dict) else None
    if config.shape == "canvas":
        return _canvas_series_rows(config, parent_id, data)
    if not isinstance(data, list):
        return []
    rows: list[dict[str, Any]] = []
    for point in data:
        if not isinstance(point, dict):
            continue
        row = dict(point)
        if config.parent_id_column is not None:
            row[config.parent_id_column] = parent_id
        rows.append(_encode_json_fields(row, config.json_fields))
    return rows


def _iter_parent_ids(
    api_key: str, base_url: str, config: BrazeDataSeriesConfig, team_id: int, job_id: str
) -> Iterator[str]:
    assert config.parent is not None and config.parent_id_field is not None
    parent_config = BRAZE_ENDPOINTS[config.parent]
    paginator, _ = _paginator_for(parent_config)
    resource = _list_resource(api_key, base_url, parent_config, team_id, job_id, paginator)
    for page in resource:
        for item in _normalize_items(parent_config, page):
            value = item.get(config.parent_id_field)
            if isinstance(value, str) and value:
                yield value


def _data_series_rows(
    api_key: str,
    base_url: str,
    config: BrazeDataSeriesConfig,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[list[dict[str, Any]]]:
    now = datetime.now(tz=UTC)
    span_days = _series_span_days(should_use_incremental_field, db_incremental_field_last_value, now.date())
    windows = _series_windows(config.max_length_days, span_days, now)

    session = make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        # No redirects: the base URL is customer-supplied, so keep traffic pinned
        # to the validated host (SSRF hardening).
        allow_redirects=False,
        redact_values=(api_key,),
    )
    url = f"{normalize_base_url(base_url)}{config.path}"

    parent_ids: Iterable[Optional[str]] = (
        _iter_parent_ids(api_key, base_url, config, team_id, job_id) if config.parent else [None]
    )
    for parent_id in parent_ids:
        for ending_at, length in windows:
            params: dict[str, Any] = {"length": length, "ending_at": ending_at.isoformat(), **config.params}
            if config.parent_id_param is not None:
                params[config.parent_id_param] = parent_id
            response = session.get(url, params=params)
            response.raise_for_status()
            rows = _series_rows(config, parent_id, response.json())
            if rows:
                yield rows


def _braze_data_series_source(
    api_key: str,
    base_url: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    config = BRAZE_DATA_SERIES_ENDPOINTS[endpoint]

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        # Re-check at run time (not just at source-create) in case the URL was edited or now
        # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
        host_ok, host_err = _is_host_safe(_host_from_url(base_url), team_id)
        if not host_ok:
            raise BrazeHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

        # No resume checkpoint: a fan-out is only resumable from a stable parent ordering, and
        # Braze's list endpoints order by last edit time, which moves between pages.
        yield from _data_series_rows(
            api_key,
            base_url,
            config,
            team_id,
            job_id,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )

    return SourceResponse(
        name=endpoint,
        items=get_rows,
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Rows arrive grouped by parent and then by window, so `time` never runs monotonically
        # across the whole stream.
        sort_mode=None,
    )


def braze_source(
    api_key: str,
    base_url: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BrazeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    if endpoint in BRAZE_DATA_SERIES_ENDPOINTS:
        return _braze_data_series_source(
            api_key,
            base_url,
            endpoint,
            team_id,
            job_id,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )

    config = BRAZE_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    if config.modified_after_param and should_use_incremental_field and db_incremental_field_last_value:
        params[config.modified_after_param] = _format_modified_after(db_incremental_field_last_value)

    paginator, state_key = _paginator_for(config)

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {state_key: resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; saved AFTER a page is yielded so a crash
        # never skips an undelivered page.
        if state and state.get(state_key) is not None:
            resumable_source_manager.save_state(BrazeResumeConfig(cursor=int(state[state_key])))

    resource = _list_resource(
        api_key,
        base_url,
        config,
        team_id,
        job_id,
        paginator,
        params=params,
        db_incremental_field_last_value=db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        # Re-check at run time (not just at source-create) in case the URL was edited or now
        # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
        host_ok, host_err = _is_host_safe(_host_from_url(base_url), team_id)
        if not host_ok:
            raise BrazeHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

        for page in resource:
            # events/list returns bare event-name strings; other endpoints may carry
            # stray non-dict rows — reshape/drop them exactly as before the migration.
            yield _normalize_items(config, page)

    return SourceResponse(
        name=endpoint,
        items=get_rows,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
