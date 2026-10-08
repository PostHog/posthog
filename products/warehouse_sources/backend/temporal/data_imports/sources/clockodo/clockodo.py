import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.settings import (
    ENTRIES_TIME_SINCE,
    USER_REPORTS_FIRST_YEAR,
    USER_REPORTS_TYPE,
    USER_REPORTS_YEAR_FIELD,
    WORK_TIMES_FIRST_DATE,
    WORK_TIMES_WINDOW_DAYS,
    ClockodoEndpointConfig,
    endpoints_for_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# Clockodo's API is hosted at a single fixed host for every account (no per-tenant subdomain).
CLOCKODO_BASE_URL = "https://my.clockodo.com/api"

# Clockodo identifies the calling application via a mandatory header formatted
# "[application name];[email address]". We send our app name plus the connecting user's email.
EXTERNAL_APPLICATION_NAME = "PostHog"

# Bounds every request the swept endpoints issue, as (connect, read) seconds. Without it a
# stalled response holds the import worker for as long as the activity deadline allows.
REQUEST_TIMEOUT_SECONDS = (10.0, 120.0)

# Endpoints that no single request can cover: work times take one co-worker and one date range
# at a time, co-worker reports take one year at a time. Both are swept in the transport instead
# of through a declarative resource.
WORK_TIMES_ENDPOINT = "work_times"
USER_REPORTS_ENDPOINT = "user_reports"


@dataclasses.dataclass
class ClockodoResumeConfig:
    # Next 1-indexed page to fetch. Only meaningful for paginated endpoints.
    next_page: int


def _build_headers(api_user: str) -> dict[str, str]:
    # The API key is supplied via the framework auth config so its value is redacted from
    # logs; only the non-secret identification/accept headers are set here.
    return {
        "X-ClockodoApiUser": api_user,
        "X-Clockodo-External-Application": f"{EXTERNAL_APPLICATION_NAME};{api_user}",
        "Accept": "application/json",
    }


def _format_z(dt: datetime) -> str:
    """ISO 8601 in UTC with a Z suffix, the format the entries endpoint expects."""
    utc_dt = dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _endpoint_params(endpoint: str, config: ClockodoEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.extra_params)
    if endpoint == "entries":
        # Send a wide window so every entry is in range. time_until is pushed a year past now
        # to also capture future-dated planned entries.
        params["time_since"] = ENTRIES_TIME_SINCE
        params["time_until"] = _format_z(datetime.now(UTC) + timedelta(days=365))
    return params


def _paginator_for(config: ClockodoEndpointConfig) -> BasePaginator:
    # Paginated responses carry the total page count at paging.count_pages, so we stop after
    # the last page. An empty page also terminates (stop_after_empty_page default).
    return (
        PageNumberPaginator(base_page=1, page_param="page", total_path="paging.count_pages")
        if config.paginated
        else SinglePagePaginator()
    )


def _rest_client(api_user: str, api_key: str) -> RESTClient:
    return RESTClient(
        base_url=CLOCKODO_BASE_URL,
        headers=_build_headers(api_user),
        # The key travels via the framework auth config so its value is redacted from logs.
        auth=APIKeyAuth(api_key=api_key, name="X-ClockodoApiKey", location="header"),
        paginator=SinglePagePaginator(),
        request_timeout=REQUEST_TIMEOUT_SECONDS,
    )


def _rows_for(
    client: RESTClient, config: ClockodoEndpointConfig, params: Optional[dict[str, Any]] = None
) -> Iterator[dict[str, Any]]:
    for page in client.paginate(
        path=config.path,
        params=params or {},
        paginator=_paginator_for(config),
        data_selector=config.data_key,
    ):
        yield from page


@frozen
class _WorkTimeWindow:
    date_since: date
    date_until: date


def _work_time_windows(today: date) -> Iterator[_WorkTimeWindow]:
    start = WORK_TIMES_FIRST_DATE
    while start <= today:
        end = min(start + timedelta(days=WORK_TIMES_WINDOW_DAYS - 1), today)
        yield _WorkTimeWindow(date_since=start, date_until=end)
        start = end + timedelta(days=1)


def _work_time_pages(
    client: RESTClient, users_config: ClockodoEndpointConfig, config: ClockodoEndpointConfig
) -> Iterator[list[dict[str, Any]]]:
    """Walk every co-worker, then every date window of that co-worker's attendance.

    The endpoint requires a single users_id plus a date range, so the co-worker list is the only
    way to reach the whole account. Rows already name their co-worker and day, so nothing has to
    be stamped on.
    """
    windows = list(_work_time_windows(datetime.now(UTC).date()))
    for user in _rows_for(client, users_config):
        users_id = user.get("id")
        if users_id is None:
            continue
        for window in windows:
            for page in client.paginate(
                path=config.path,
                params={
                    "users_id": users_id,
                    "date_since": window.date_since.isoformat(),
                    "date_until": window.date_until.isoformat(),
                },
                paginator=SinglePagePaginator(),
                data_selector=config.data_key,
            ):
                if page:
                    yield page


def _user_report_pages(client: RESTClient, config: ClockodoEndpointConfig) -> Iterator[list[dict[str, Any]]]:
    """Walk one year of co-worker reports at a time, stamping the year onto each row."""
    for year in range(USER_REPORTS_FIRST_YEAR, datetime.now(UTC).year + 1):
        rows = [
            {**row, USER_REPORTS_YEAR_FIELD: year}
            for row in _rows_for(client, config, params={"year": year, "type": USER_REPORTS_TYPE})
        ]
        if rows:
            yield rows


def clockodo_source(
    api_user: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ClockodoResumeConfig],
    api_version: str,
) -> SourceResponse:
    endpoints = endpoints_for_version(api_version)
    config = endpoints[endpoint]

    # The swept endpoints issue one request per co-worker or per year, so a saved page number
    # would point into a single request rather than at the sweep's position — they restart
    # instead of resuming, which a full refresh tolerates.
    if endpoint == WORK_TIMES_ENDPOINT:
        client = _rest_client(api_user, api_key)
        users_config = endpoints["users"]
        return SourceResponse(
            name=endpoint,
            items=lambda: _work_time_pages(client, users_config, config),
            primary_keys=config.primary_keys,
        )

    if endpoint == USER_REPORTS_ENDPOINT:
        client = _rest_client(api_user, api_key)
        return SourceResponse(
            name=endpoint,
            items=lambda: _user_report_pages(client, config),
            primary_keys=config.primary_keys,
        )

    # Clockodo only paginates a subset of resources.
    paginator: BasePaginator = _paginator_for(config)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CLOCKODO_BASE_URL,
            "headers": _build_headers(api_user),
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-ClockodoApiKey", "location": "header"},
            "paginator": paginator,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": _endpoint_params(endpoint, config),
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash
        # re-fetches the last in-flight page (merge dedupes on the primary key) rather than
        # skipping it. Unpaginated endpoints never produce a state, so they never checkpoint.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(ClockodoResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every Clockodo endpoint is full refresh — no incremental fields
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
    )


def validate_credentials(api_user: str, api_key: str, api_version: str) -> bool:
    """Cheap probe to confirm the API user/key pair is genuine.

    Probes the users endpoint for the resolved version so a new source (default v3) does not
    validate against `v2/users`, which is decommissioned on 2026-05-01.
    """
    users_path = endpoints_for_version(api_version)["users"].path
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{CLOCKODO_BASE_URL}/{users_path}",
        headers={"X-ClockodoApiKey": api_key, **_build_headers(api_user)},
    )
    return ok
