import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from requests import Session
from requests.exceptions import RequestException

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.clover.settings import (
    CLOVER_ENDPOINTS,
    CLOVER_REGION_HOSTS,
    FILTER_WINDOW_MS,
    CloverEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

MERCHANT_ID_PATTERN = re.compile(r"[A-Za-z0-9]+")
CONNECT_TIMEOUT_SECONDS = 10
READ_TIMEOUT_SECONDS = 120
PROBE_READ_TIMEOUT_SECONDS = 15
REQUEST_HEADERS = {"Accept": "application/json", "User-Agent": "PostHog/1.0"}


@frozen
class CloverResumeConfig:
    paginator_state: dict[str, Any]


def base_url(region: str) -> str:
    host = CLOVER_REGION_HOSTS.get(region)
    if host is None:
        raise ValueError(f"Unknown Clover region: {region}")
    return host


def _now_ms() -> int:
    return round(datetime.now(tz=UTC).timestamp() * 1000)


def _tracked_session(auth: AuthConfigBase) -> Session:
    # Customer names and payment details must stay out of response samples.
    return make_tracked_session(redact_values=auth.secret_values(), capture=False)


def _merchant_path(merchant_id: str, path: str, api_version: str) -> str:
    if not MERCHANT_ID_PATTERN.fullmatch(merchant_id):
        raise ValueError("Clover merchant ID must be alphanumeric")
    if api_version != "v3":
        raise ValueError(f"Unsupported Clover API version: {api_version}")
    return f"/{api_version}/merchants/{merchant_id}/{path}".rstrip("/")


def validate_credentials(
    region: str,
    merchant_id: str,
    auth: AuthConfigBase,
    api_version: str,
    schema_name: str | None = None,
) -> tuple[bool, str | None]:
    config = CLOVER_ENDPOINTS.get(schema_name) if schema_name is not None else None
    if schema_name is not None and config is None:
        return False, "Unknown Clover table. Select a supported table."
    if config is not None and config.fanout is not None:
        config = CLOVER_ENDPOINTS[config.fanout.parent_name]
    try:
        url = base_url(region) + _merchant_path(merchant_id, config.path if config else "", api_version)
    except ValueError as error:
        return False, str(error)

    try:
        with _tracked_session(auth) as session:
            response = session.get(
                url,
                params={"limit": 1} if config else None,
                headers=REQUEST_HEADERS,
                auth=auth,
                allow_redirects=False,
                timeout=(CONNECT_TIMEOUT_SECONDS, PROBE_READ_TIMEOUT_SECONDS),
            )
    except RequestException:
        return False, "Could not connect to Clover. Try again."

    if response.status_code == 401:
        return False, "Clover rejected your credentials. Update the API token."
    if response.status_code == 403:
        if schema_name is None:
            return True, None
        assert config is not None
        return False, f"Clover requires the '{config.permission}' permission. Grant it and try again."
    if response.status_code == 404:
        return False, "Clover could not find this merchant or table. Check the merchant ID and region."
    if response.status_code != 200:
        return False, f"Clover returned HTTP {response.status_code}. Check your connection and try again."
    return True, None


def endpoint_permissions(
    region: str,
    merchant_id: str,
    endpoints: list[str],
    auth: AuthConfigBase,
    api_version: str,
) -> dict[str, str | None]:
    host = base_url(region)
    results: dict[str, str | None] = {}
    with _tracked_session(auth) as session:
        for name in endpoints:
            config = CLOVER_ENDPOINTS.get(name)
            if config is None:
                results[name] = None
                continue
            probe = CLOVER_ENDPOINTS[config.fanout.parent_name] if config.fanout else config
            try:
                response = session.get(
                    host + _merchant_path(merchant_id, probe.path, api_version),
                    params={"limit": 1},
                    headers=REQUEST_HEADERS,
                    auth=auth,
                    allow_redirects=False,
                    timeout=(CONNECT_TIMEOUT_SECONDS, PROBE_READ_TIMEOUT_SECONDS),
                )
            except RequestException:
                results[name] = None
                continue
            results[name] = (
                f"Clover requires the '{config.permission}' permission. Grant it and try again."
                if response.status_code in (401, 403)
                else None
            )
    return results


def _endpoint(config: CloverEndpointConfig, path: str) -> Endpoint:
    return {
        "path": path,
        "params": dict(config.params),
        "paginator": {"type": "offset", "limit": config.page_size, "total_path": None},
        "data_selector": "elements",
        "data_selector_required": True,
    }


def _normalize_row(row: dict[str, Any], config: CloverEndpointConfig, window: tuple[int, int] | None) -> dict[str, Any]:
    if config.partition_field is not None:
        value = row.get(config.partition_field)
        if value is None and window is not None:
            raise ValueError(f"Clover returned no {config.partition_field} timestamp for a history window")
        if value is not None:
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"Clover returned an invalid {config.partition_field} timestamp")
            if window is not None and not window[0] <= value <= window[1]:
                raise ValueError("Clover returned a row outside the requested history window")
            row["created_at"] = datetime.fromtimestamp(value / 1000, tz=UTC)
    return row


def clover_source(
    region: str,
    merchant_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CloverResumeConfig],
    auth: AuthConfigBase,
    api_version: str,
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    if should_use_incremental_field:
        raise ValueError("Clover supports full refresh only. Change the table sync mode to full refresh.")
    config = CLOVER_ENDPOINTS[endpoint]
    host = base_url(region)
    path = _merchant_path(merchant_id, config.path, api_version)
    parent = CLOVER_ENDPOINTS[config.fanout.parent_name] if config.fanout else config

    def items() -> Iterator[list[dict[str, Any]]]:
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        state = resume.paginator_state if resume else {}
        if state.get("completed"):
            return
        end_ms = int(state.get("end_ms", _now_ms()))
        start_ms = int(state.get("window_start_ms") or 0)
        resource_state = state.get("resource_state")
        if resource_state is None and "offset" in state:
            resource_state = {"offset": state["offset"]}

        with _tracked_session(auth) as session:
            client_config: ClientConfig = {
                "base_url": host,
                "headers": REQUEST_HEADERS,
                "auth": auth,
                "session": session,
                "allowed_hosts": [],
                "allow_redirects": False,
                "request_timeout": (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            }
            first_window = True
            while start_ms <= end_ms:
                window_end = min(start_ms + FILTER_WINDOW_MS - 1, end_ms)
                window = (start_ms, window_end) if parent.history_field else None
                if not first_window:
                    # Stage each later window's start before its rows, so no save has to follow a yield.
                    resumable_source_manager.save_state(
                        CloverResumeConfig(
                            paginator_state={
                                "window_start_ms": start_ms,
                                "end_ms": end_ms,
                                "resource_state": None,
                                "completed": False,
                            }
                        )
                    )
                params = dict(parent.params)
                if window is not None:
                    # Clover can limit unfiltered history to 90 days, so backfills also need date windows.
                    params["filter"] = [
                        f"{parent.history_field}>={start_ms}",
                        f"{parent.history_field}<={window_end}",
                    ]

                def save_checkpoint(
                    next_state: dict[str, Any] | None,
                    *,
                    window_start: int = start_ms,
                    window_stop: int = window_end,
                    has_window: bool = window is not None,
                ) -> None:
                    # The framework calls this after yielding each page to prevent skipped rows on retries.
                    resumable_source_manager.save_state(
                        CloverResumeConfig(
                            paginator_state={
                                "window_start_ms": window_start if next_state else window_stop + 1,
                                "end_ms": end_ms,
                                "resource_state": next_state,
                                "completed": next_state is None and (not has_window or window_stop == end_ms),
                            }
                        )
                    )

                if config.fanout is not None:
                    endpoint_configs = {
                        name: dataclasses.replace(value, path=_merchant_path(merchant_id, value.path, api_version))
                        for name, value in CLOVER_ENDPOINTS.items()
                    }
                    resource = build_dependent_resource(
                        endpoint_configs=endpoint_configs,
                        child_endpoint=endpoint,
                        fanout=dataclasses.replace(config.fanout, parent_params=params),
                        client_config=client_config,
                        path_format_values={},
                        team_id=team_id,
                        job_id=job_id,
                        db_incremental_field_last_value=None,
                        parent_endpoint_extra={
                            "paginator": {"type": "offset", "limit": parent.page_size, "total_path": None},
                            "data_selector": "elements",
                            "data_selector_required": True,
                        },
                        child_endpoint_extra={
                            "paginator": {"type": "offset", "limit": config.page_size, "total_path": None},
                            "data_selector": "elements",
                            "data_selector_required": True,
                        },
                        child_params_extra=config.params,
                        resume_hook=save_checkpoint,
                        initial_paginator_state=resource_state,
                    )
                    for page in resource:
                        yield [_normalize_row(row, config, window) for row in page]
                        resumable_source_manager.safe_point()
                else:
                    endpoint_config = _endpoint(config, path)
                    endpoint_config["params"] = params
                    rest_config: RESTAPIConfig = {
                        "client": client_config,
                        "resources": [
                            {
                                "name": endpoint,
                                "table_name": endpoint,
                                "write_disposition": "replace",
                                "endpoint": endpoint_config,
                                "table_format": "delta",
                            }
                        ],
                    }
                    resource = rest_api_resource(
                        rest_config,
                        team_id,
                        job_id,
                        None,
                        resume_hook=save_checkpoint,
                        initial_paginator_state=resource_state,
                    )
                    for page in resource:
                        yield [_normalize_row(row, config, window) for row in page]
                        resumable_source_manager.safe_point()
                if window is None:
                    break
                start_ms = window_end + 1
                resource_state = None
                first_window = False
        resumable_source_manager.save_state(
            CloverResumeConfig(
                paginator_state={
                    "window_start_ms": start_ms,
                    "end_ms": end_ms,
                    "resource_state": None,
                    "completed": True,
                }
            )
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        partition_keys=["created_at"] if config.partition_field else config.primary_keys,
        partition_mode="datetime" if config.partition_field else "md5",
        partition_format="month" if config.partition_field else None,
        partition_count=None if config.partition_field else 16,
        sort_mode="desc",
    )
