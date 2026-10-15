from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlparse

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.litellm.settings import (
    LIST_PAGE_SIZE,
    LITELLM_ENDPOINTS,
    SPEND_LOGS_FIELD,
    SPEND_LOGS_PAGE_SIZE,
    SPEND_LOGS_WINDOW,
    LiteLLMEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
# The lower bound of the one query that finds the oldest spend log on a full refresh.
SPEND_LOGS_EARLIEST = datetime(2000, 1, 1, tzinfo=UTC)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

SPEND_LOGS_UNAVAILABLE_MESSAGE = (
    "This LiteLLM proxy has no /spend/logs/v2 endpoint. Upgrade LiteLLM to a recent version, then sync again."
)


class LiteLLMSpendLogsUnavailableError(Exception):
    pass


@dataclass(frozen=True)
class LiteLLMResumeConfig:
    page: int | None = None
    window_start: str | None = None
    run_end: str | None = None
    # Whether an earlier window already yielded the rows at exactly `window_start`.
    window_start_seen: bool = False


def normalize_base_url(base_url: str) -> str:
    """Return the proxy's https origin plus any path prefix, or raise ValueError.

    The key travels in a header to a host the user chose, so plain http is refused, and so are the
    constructs (`\\`, encoded `@`, userinfo) that make `urlparse` and the HTTP client disagree on the
    target host, which would let the host check approve one host while the request goes to another.
    """
    url = base_url.strip()
    if not url:
        raise ValueError("LiteLLM base URL is required")
    if "://" not in url:
        url = f"https://{url}"
    url = url.rstrip("/")
    lowered = url.lower()
    if "\\" in url or "%5c" in lowered or "%40" in lowered:
        raise ValueError(f"Invalid LiteLLM base URL: {url}")
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        raise ValueError(f"Invalid LiteLLM base URL: {url}")
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"Invalid LiteLLM base URL (must be https): {url}")
    host_part = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    if parsed.netloc.lower() != (host_part + (f":{port}" if port else "")).lower():
        raise ValueError(f"Invalid LiteLLM base URL: {url}")
    if parsed.query or parsed.fragment:
        raise ValueError(f"Invalid LiteLLM base URL: {url}")
    return f"https://{parsed.netloc}{parsed.path}"


def hostname_of(base_url: str) -> str:
    return urlparse(normalize_base_url(base_url)).hostname or ""


def _session(api_key: str) -> requests.Session:
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        redact_values=(api_key,),
        allow_redirects=False,
    )


def _fetch_spend_logs(
    session: requests.Session, base_url: str, start: datetime, end: datetime, page: int, page_size: int
) -> dict[str, Any]:
    params = {
        "start_date": start.strftime(_DATE_FORMAT),
        "end_date": end.strftime(_DATE_FORMAT),
        "page": page,
        "page_size": page_size,
        "sort_by": SPEND_LOGS_FIELD,
        "sort_order": "asc",
    }
    response = session.get(f"{base_url}/spend/logs/v2?{urlencode(params)}", timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code == 404:
        raise LiteLLMSpendLogsUnavailableError(SPEND_LOGS_UNAVAILABLE_MESSAGE)
    response.raise_for_status()
    return response.json()


def _as_utc(value: Any) -> datetime | None:
    parsed = parse_datetime_value(value)
    if parsed is None:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def spend_log_pages(
    session: requests.Session,
    base_url: str,
    resumable_source_manager: ResumableSourceManager[LiteLLMResumeConfig],
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Yield spend logs oldest first, one page at a time, walking day-long windows up to the run start."""
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    # Both date bounds are inclusive, so a window repeats rows at exactly its start that the window
    # before it already yielded. Only the first window of a fresh run has no predecessor.
    repeated_start: datetime | None = None
    if resume is not None and resume.window_start is not None and resume.run_end is not None:
        start = datetime.fromisoformat(resume.window_start)
        run_end = datetime.fromisoformat(resume.run_end)
        page = resume.page or 1
        repeated_start = start if resume.window_start_seen else None
    else:
        run_end = datetime.now(UTC).replace(microsecond=0)
        page = 1
        start_value = _as_utc(db_incremental_field_last_value)
        if start_value is None:
            oldest = _fetch_spend_logs(session, base_url, SPEND_LOGS_EARLIEST, run_end, page=1, page_size=1)
            start_value = _as_utc(oldest["data"][0][SPEND_LOGS_FIELD]) if oldest.get("data") else None
            if start_value is None:
                return
        start = start_value.replace(microsecond=0)

    while True:
        end = min(start + SPEND_LOGS_WINDOW, run_end)
        body = _fetch_spend_logs(session, base_url, start, end, page, SPEND_LOGS_PAGE_SIZE)
        page_rows: list[dict[str, Any]] = body.get("data") or []
        total_pages = body.get("total_pages")
        # LiteLLM stops counting at 10,000 matches and flags it, so a capped `total_pages` is a floor.
        if body.get("total_is_capped") or not isinstance(total_pages, int):
            has_next_page = len(page_rows) == SPEND_LOGS_PAGE_SIZE
        else:
            has_next_page = page < total_pages
        last_window = end >= run_end
        rows = [
            row for row in page_rows if repeated_start is None or _as_utc(row.get(SPEND_LOGS_FIELD)) != repeated_start
        ]

        if has_next_page:
            next_state: LiteLLMResumeConfig | None = LiteLLMResumeConfig(
                window_start=start.isoformat(),
                run_end=run_end.isoformat(),
                page=page + 1,
                window_start_seen=repeated_start is not None,
            )
        elif not last_window:
            next_state = LiteLLMResumeConfig(
                window_start=end.isoformat(), run_end=run_end.isoformat(), page=1, window_start_seen=True
            )
        else:
            next_state = None

        if next_state is not None:
            resumable_source_manager.save_state(next_state)
        if rows:
            yield rows
        elif next_state is not None:
            resumable_source_manager.safe_point()

        if next_state is None:
            return
        if next_state.page == 1:
            repeated_start = end
        start = datetime.fromisoformat(next_state.window_start or "")
        page = next_state.page or 1


def _with_model_id(row: dict[str, Any]) -> dict[str, Any]:
    # `/model/info` keeps the deployment id inside `model_info`, so lift it to key the table.
    model_info = row.get("model_info")
    return {**row, "model_id": model_info.get("id") if isinstance(model_info, dict) else None}


def _without_key_config(row: dict[str, Any]) -> dict[str, Any]:
    # A key's `config` can hold a model list with provider API keys.
    return {name: value for name, value in row.items() if name != "config"}


def _without_team_keys(row: dict[str, Any]) -> dict[str, Any]:
    # Team rows embed full key objects, credentials included; the keys table has them without.
    return {name: value for name, value in row.items() if name != "keys"}


_ROW_MAPS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "keys": _without_key_config,
    "teams": _without_team_keys,
    "models": _with_model_id,
}


def _list_resource(
    config: LiteLLMEndpointConfig,
    base_url: str,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LiteLLMResumeConfig],
) -> Any:
    params: dict[str, Any] = {}
    paginator: BasePaginator = SinglePagePaginator()
    if config.page_size_param is not None:
        params[config.page_size_param] = LIST_PAGE_SIZE
        paginator = PageNumberPaginator(base_page=1, page_param="page", total_path="total_pages")
    if config.name == "keys":
        params["return_full_object"] = "true"

    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "table_format": "delta",
        "endpoint": {
            "path": config.path,
            "params": params,
            "data_selector": config.data_selector,
            "paginator": paginator,
        },
    }
    if config.name in _ROW_MAPS:
        resource["data_map"] = _ROW_MAPS[config.name]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [resource],
    }

    initial_paginator_state: dict[str, Any] | None = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.page is not None and resume.window_start is None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None and state.get("page") is not None:
            resumable_source_manager.save_state(LiteLLMResumeConfig(page=int(state["page"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def litellm_source(
    base_url: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LiteLLMResumeConfig],
    db_incremental_field_last_value: Any,
) -> SourceResponse:
    config = LITELLM_ENDPOINTS[endpoint]
    origin = normalize_base_url(base_url)
    partitioning: dict[str, Any] = (
        {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [config.partition_key],
        }
        if config.partition_key
        else {}
    )

    if endpoint == "spend_logs":
        session = _session(api_key)
        return SourceResponse(
            name=endpoint,
            items=lambda: spend_log_pages(session, origin, resumable_source_manager, db_incremental_field_last_value),
            primary_keys=[config.primary_key],
            sort_mode="asc",
            **partitioning,
        )

    resource = _list_resource(config, origin, api_key, team_id, job_id, resumable_source_manager)
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        column_hints=resource.column_hints,
        **partitioning,
    )


def probe_key(base_url: str, api_key: str) -> int | None:
    """Status of a one-row key listing, or None when unreachable.

    `/key/info` would 404 for a master key, because it looks the calling key up as a stored key.
    """
    try:
        response = _session(api_key).get(f"{normalize_base_url(base_url)}/key/list?page=1&size=1", timeout=15)
    except requests.RequestException:
        return None
    return response.status_code
