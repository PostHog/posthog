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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
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
_REDACTED = "[redacted by PostHog]"

SPEND_LOGS_UNAVAILABLE_MESSAGE = (
    "This LiteLLM proxy's /spend/logs/v2 endpoint is missing or too old. "
    "Upgrade LiteLLM to version 1.84 or later, then sync again."
)


class LiteLLMSpendLogsUnavailableError(Exception):
    pass


@dataclass(frozen=True)
class LiteLLMResumeConfig:
    page: int | None = None
    # Spend logs only: the second the next request starts at, the end of the run, and the logs at
    # that second an earlier page already yielded.
    cursor: str | None = None
    run_end: str | None = None
    seen_request_ids: tuple[str, ...] = ()


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
    # 404: no v2 endpoint. 422: a version that refuses this page size or sort.
    if response.status_code in (404, 422):
        raise LiteLLMSpendLogsUnavailableError(SPEND_LOGS_UNAVAILABLE_MESSAGE)
    response.raise_for_status()
    return response.json()


def _as_utc(value: Any) -> datetime | None:
    parsed = parse_datetime_value(value)
    if parsed is None:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _request_ids_at(rows: list[dict[str, Any]], times: list[datetime | None], second: datetime) -> tuple[str, ...]:
    return tuple(
        str(row.get("request_id"))
        for row, time in zip(rows, times)
        if time is not None and time.replace(microsecond=0) == second
    )


def _first_log_time(session: requests.Session, base_url: str, start: datetime, end: datetime) -> datetime | None:
    """The time of the first log in `[start, end]`, or None when there is none.

    Two logs are read, so a proxy that ignores `sort_order` shows itself before its newest log is
    taken for the oldest.
    """
    body = _fetch_spend_logs(session, base_url, start, end, page=1, page_size=2)
    times = [_as_utc(row.get(SPEND_LOGS_FIELD)) for row in body.get("data") or []]
    if len(times) == 2 and times[0] and times[1] and times[1] < times[0]:
        raise LiteLLMSpendLogsUnavailableError(SPEND_LOGS_UNAVAILABLE_MESSAGE)
    return times[0] if times else None


def spend_log_pages(
    session: requests.Session,
    base_url: str,
    resumable_source_manager: ResumableSourceManager[LiteLLMResumeConfig],
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Yield spend logs oldest first, moving `start_date` up to the last log of each full page.

    LiteLLM pages with a SQL offset, which gets slow deep into a busy proxy's history. Restarting
    at page 1 from the last log keeps every offset at zero. The date bounds are inclusive, so the
    logs at the cursor second come back and are dropped by `request_id`.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.cursor is not None and resume.run_end is not None:
        cursor = datetime.fromisoformat(resume.cursor)
        run_end = datetime.fromisoformat(resume.run_end)
        page = resume.page or 1
        seen = set(resume.seen_request_ids)
    else:
        run_end = datetime.now(UTC).replace(microsecond=0)
        page = 1
        seen = set()
        start = _as_utc(db_incremental_field_last_value) or _first_log_time(
            session, base_url, SPEND_LOGS_EARLIEST, run_end
        )
        if start is None:
            return
        cursor = start.replace(microsecond=0)

    while True:
        end = min(cursor + SPEND_LOGS_WINDOW, run_end)
        body = _fetch_spend_logs(session, base_url, cursor, end, page, SPEND_LOGS_PAGE_SIZE)
        page_rows: list[dict[str, Any]] = body.get("data") or []
        times = [_as_utc(row.get(SPEND_LOGS_FIELD)) for row in page_rows]
        # Old proxies ignore `sort_order` and return newest first, which would break the cursor.
        if any(earlier and later and later < earlier for earlier, later in zip(times, times[1:])):
            raise LiteLLMSpendLogsUnavailableError(SPEND_LOGS_UNAVAILABLE_MESSAGE)
        rows = [row for row in page_rows if row.get("request_id") not in seen]

        next_state: LiteLLMResumeConfig | None = None
        if len(page_rows) == SPEND_LOGS_PAGE_SIZE:
            last_second = times[-1].replace(microsecond=0) if times[-1] else None
            if last_second is None or last_second <= cursor:
                # A full page inside one second cannot move the cursor, so step past it by page.
                next_state = LiteLLMResumeConfig(
                    cursor=cursor.isoformat(),
                    run_end=run_end.isoformat(),
                    page=page + 1,
                    seen_request_ids=tuple(sorted(seen)),
                )
            else:
                next_state = LiteLLMResumeConfig(
                    cursor=last_second.isoformat(),
                    run_end=run_end.isoformat(),
                    page=1,
                    seen_request_ids=_request_ids_at(page_rows, times, last_second),
                )
        elif end < run_end and page_rows:
            next_state = LiteLLMResumeConfig(
                cursor=end.isoformat(),
                run_end=run_end.isoformat(),
                page=1,
                seen_request_ids=_request_ids_at(page_rows, times, end),
            )
        elif end < run_end:
            # An empty day: jump to the next log instead of walking an idle proxy one day at a time.
            next_log = _first_log_time(session, base_url, end, run_end)
            if next_log is not None:
                # Never land before the empty window's end, so a nonconforming response cannot stall the walk.
                jump = max(next_log.replace(microsecond=0), end)
                next_state = LiteLLMResumeConfig(cursor=jump.isoformat(), run_end=run_end.isoformat(), page=1)

        if next_state is not None:
            resumable_source_manager.save_state(next_state)
        if rows:
            yield rows
        elif next_state is not None:
            resumable_source_manager.safe_point()

        if next_state is None:
            return
        cursor = datetime.fromisoformat(next_state.cursor or "")
        page = next_state.page or 1
        seen = set(next_state.seen_request_ids)


def _with_model_id(row: dict[str, Any]) -> dict[str, Any]:
    # `/model/info` keeps the deployment id inside `model_info`, so lift it to key the table.
    model_info = row.get("model_info")
    return {**row, "model_id": model_info.get("id") if isinstance(model_info, dict) else None}


def _redact_credentials(metadata: Any) -> Any:
    """Mask the credentials LiteLLM keeps in key and team metadata.

    Logging credentials such as `langfuse_secret_key` sit in `callback_vars`; their names stay, so
    the table still shows which logging integrations are configured. LiteLLM masks the same two
    places before it writes its own audit log. `secret_manager_settings` can hold cloud credentials
    for the proxy's secret manager, so it is dropped.
    """
    if not isinstance(metadata, dict):
        return metadata
    redacted = {name: value for name, value in metadata.items() if name != "secret_manager_settings"}
    if isinstance(redacted.get("logging"), list):
        redacted["logging"] = [
            {**entry, "callback_vars": dict.fromkeys(entry["callback_vars"], _REDACTED)}
            if isinstance(entry, dict) and isinstance(entry.get("callback_vars"), dict)
            else entry
            for entry in redacted["logging"]
        ]
    settings = redacted.get("callback_settings")
    if isinstance(settings, dict) and isinstance(settings.get("callback_vars"), dict):
        redacted["callback_settings"] = {
            **settings,
            "callback_vars": dict.fromkeys(settings["callback_vars"], _REDACTED),
        }
    return redacted


def _shape_key(row: dict[str, Any]) -> dict[str, Any]:
    # A key's `config` can hold a model list with provider API keys.
    shaped = {name: value for name, value in row.items() if name != "config"}
    if "metadata" in shaped:
        shaped["metadata"] = _redact_credentials(shaped["metadata"])
    return shaped


def _shape_team(row: dict[str, Any]) -> dict[str, Any]:
    # Some versions embed full key objects in team rows; the keys table already has them, shaped.
    shaped = {name: value for name, value in row.items() if name != "keys"}
    if "metadata" in shaped:
        shaped["metadata"] = _redact_credentials(shaped["metadata"])
    return shaped


_ROW_MAPS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "keys": _shape_key,
    "teams": _shape_team,
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
            "capture": config.capture,
        },
        "resource_defaults": {},
        "resources": [resource],
    }

    initial_paginator_state: dict[str, Any] | None = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.page is not None and resume.cursor is None:
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
    _, status = validate_via_probe(
        lambda: _session(api_key),
        f"{normalize_base_url(base_url)}/key/list?page=1&size=1",
        timeout=15,
        allow_redirects=False,
    )
    return status
