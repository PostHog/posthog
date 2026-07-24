import dataclasses
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.settings import SMARTWAIVER_ENDPOINTS

SMARTWAIVER_BASE_URL = "https://api.smartwaiver.com"
# /v4/waivers documents limit 1-300 and /v4/checkins documents 1-100; 100 keeps every endpoint on
# the largest page size both allow.
PAGE_SIZE = 100
# /v4/checkins caps `offset` at 1000. Past that the remainder of the window can't be paged, so we
# stop rather than loop.
CHECKINS_MAX_OFFSET = 1000
# /v4/checkins requires `fromDts`; on a full sync we use a date safely before any Smartwaiver data.
DEFAULT_FROM_DTS = "2000-01-01T00:00:00"
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every endpoint.
DEFAULT_PROBE_PATH = "/v4/templates"


@dataclasses.dataclass
class SmartwaiverResumeConfig:
    # Next zero-based page to fetch. The `fromDts`/`toDts` window is persisted alongside it so a
    # resumed job continues the exact query it was paging through; merge dedupes any re-pulled page
    # on the primary key.
    next_offset: int = 0
    from_dts: str | None = None
    to_dts: str | None = None


def _format_dts(value: Any) -> str:
    """Format an incremental cursor as the ISO 8601 string Smartwaiver expects for `fromDts`/`toDts`.

    The API interprets values as UTC; timestamps in responses come back as naive UTC strings
    ("2018-01-01 12:32:16"), which `fromisoformat` parses directly.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, str):
        try:
            return _format_dts(datetime.fromisoformat(value))
        except ValueError:
            return value
    return str(value)


def _start_of_current_hour(now: datetime) -> datetime:
    aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return aware.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _clamp_before_current_hour(value: Any, now: datetime) -> str:
    """Clamp a cursor so it satisfies the API's "must not be within the current hour" rule.

    Anything the clamp re-pulls is deduped on the primary key by the merge.
    """
    boundary = _start_of_current_hour(now) - timedelta(seconds=1)
    formatted = _format_dts(value)
    boundary_formatted = boundary.strftime("%Y-%m-%dT%H:%M:%S")
    # Both strings are naive-UTC ISO 8601, so lexicographic comparison is chronological.
    return min(formatted, boundary_formatted)


def _inject_offset(request: Request, offset: int) -> None:
    if request.params is None:
        request.params = {}
    request.params["offset"] = offset


class _PageOffsetPaginator(BasePaginator):
    """`/v4/waivers` pagination: `offset` is a zero-based PAGE index (not a row offset), incremented
    by one per page. There is no has-more flag, so a partial (or empty) page means the end."""

    def __init__(self, page_size: int, offset: int = 0) -> None:
        super().__init__()
        self.page_size = page_size
        self.offset = offset

    def init_request(self, request: Request) -> None:
        _inject_offset(request, self.offset)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data is None or len(data) < self.page_size:
            self._has_next_page = False
            return
        self.offset += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        _inject_offset(request, self.offset)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"offset": self.offset} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self.offset = int(offset)
            self._has_next_page = True


class _CheckinsPaginator(BasePaginator):
    """`/v4/checkins` pagination: `offset` is a zero-based PAGE index. The payload carries a
    `moreCheckins` flag; the API rejects offsets past `max_offset`, so a window with more results
    past the cap terminates (the next incremental sync restarts from the advanced watermark)."""

    def __init__(self, max_offset: int, offset: int = 0) -> None:
        super().__init__()
        self.max_offset = max_offset
        self.offset = offset

    def init_request(self, request: Request) -> None:
        _inject_offset(request, self.offset)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
            payload = body.get("checkins") if isinstance(body, dict) else None
            more = bool(payload.get("moreCheckins")) if isinstance(payload, dict) else False
        except Exception:
            more = False

        if not more:
            self._has_next_page = False
            return
        # The API rejects offsets past the cap, so the remainder of this window is unreachable in
        # one sync — stop here instead of requesting a page the API would reject.
        if self.offset >= self.max_offset:
            self._has_next_page = False
            return
        self.offset += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        _inject_offset(request, self.offset)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"offset": self.offset} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self.offset = int(offset)
            self._has_next_page = True


def smartwaiver_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SmartwaiverResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SMARTWAIVER_ENDPOINTS[endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    now = datetime.now(UTC)

    from_dts: str | None = None
    to_dts: str | None = None
    offset = 0
    params: dict[str, Any] = {}
    paginator: BasePaginator
    data_selector: str

    if endpoint == "templates":
        # No pagination — the endpoint returns every template in one response.
        paginator = SinglePagePaginator()
        data_selector = "templates"
    elif endpoint == "waivers":
        if resume is not None:
            offset, from_dts = resume.next_offset, resume.from_dts
        else:
            from_dts = (
                _clamp_before_current_hour(db_incremental_field_last_value, now)
                if should_use_incremental_field and db_incremental_field_last_value
                else None
            )
        # `fromDts` is dropped by the client when None (full refresh).
        params = {"limit": PAGE_SIZE, "fromDts": from_dts}
        paginator = _PageOffsetPaginator(PAGE_SIZE, offset=offset)
        data_selector = "waivers"
    elif endpoint == "checkins":
        if resume is not None:
            offset, from_dts, to_dts = resume.next_offset, resume.from_dts, resume.to_dts
        else:
            # Both bounds are required: `fromDts` must not be within the current hour and `toDts`
            # must be before it, so incremental check-in data lags real time by up to an hour. Rows
            # landing after `toDts` are picked up by the next sync (`fromDts` restarts from the
            # watermark).
            cursor = (
                db_incremental_field_last_value
                if should_use_incremental_field and db_incremental_field_last_value
                else DEFAULT_FROM_DTS
            )
            from_dts = _clamp_before_current_hour(cursor, now)
            to_dts = (_start_of_current_hour(now) - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S")
        params = {"fromDts": from_dts, "toDts": to_dts, "limit": PAGE_SIZE}
        paginator = _CheckinsPaginator(CHECKINS_MAX_OFFSET, offset=offset)
        # The check-in list nests inside the `checkins` payload object that also carries `moreCheckins`.
        data_selector = "checkins.checkins"
    else:
        raise ValueError(f"No fetcher implemented for Smartwaiver endpoint '{endpoint}'")

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SMARTWAIVER_BASE_URL,
            # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
            # logs and raised errors; only the non-secret accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": data_selector,
                    "paginator": paginator,
                },
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it. The window is persisted alongside
        # the offset so a resumed job continues the exact query it was paging through.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(
                SmartwaiverResumeConfig(next_offset=int(state["offset"]), from_dts=from_dts, to_dts=to_dts)
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # The docs don't state the list order and the related search endpoint defaults to
        # newest-first, so declare "desc": the watermark then only advances once a sync completes,
        # which is correct for either actual order.
        sort_mode="desc",
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the API key.

    The API key is account-wide, so one probe validates access to every endpoint.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{SMARTWAIVER_BASE_URL}{DEFAULT_PROBE_PATH}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Smartwaiver API key"
    if status is None:
        return False, "Could not validate Smartwaiver API key"
    return False, f"Smartwaiver returned HTTP {status}"
