import dataclasses
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any, Optional, cast

from requests.exceptions import RequestException

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.apitally.settings import (
    APITALLY_BASE_URL,
    APITALLY_ENDPOINTS,
    ApitallyEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@dataclasses.dataclass
class ApitallyResumeConfig:
    """Resume state for Apitally endpoints.

    ``Apps`` and ``Endpoints`` are unpaginated (the API returns the whole collection in one
    response), so there is never a page to resume to. ``Consumers``, ``Traffic``, and
    ``RequestLogs`` are single-hop fan-out children of ``Apps`` built with
    ``build_dependent_resource``, which does not currently expose a resume hook for dependent
    resources (see the same limitation noted on Sentry's fan-out endpoints) — so none of
    Apitally's endpoints checkpoint mid-sync today. The field below is kept for forward
    compatibility if the framework grows dependent-resource resume support.
    """

    next_token: Optional[str] = None


def _format_apitally_datetime(value: Any) -> str:
    """Format a date/datetime-like value as the `YYYY-MM-DDTHH:MM:SSZ` string Apitally's
    `start`/`end` filters document. Falls back to `str(value)` for values that are already
    a formatted string (e.g. our own `initial_value` seed)."""
    normalized = coerce_datetime_to_utc(value)
    if normalized is None:
        return str(value)
    capped = min(normalized, datetime.now(UTC))
    return capped.strftime("%Y-%m-%dT%H:%M:%SZ")


def _incremental_window(cursor_path: str) -> IncrementalConfig:
    return {
        "cursor_path": cursor_path,
        "start_param": "start",
        "end_param": "end",
        "initial_value": "1970-01-01T00:00:00Z",
        "end_value": _format_apitally_datetime(datetime.now(UTC)),
        "convert": _format_apitally_datetime,
    }


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": APITALLY_BASE_URL,
        "auth": {"type": "api_key", "name": "Api-Key", "api_key": api_key, "location": "header"},
        "headers": {"Accept": "application/json"},
        "paginator": JSONResponseCursorPaginator(cursor_path="next_token", cursor_param="next_token"),
        # `requests` only strips its built-in `Authorization` header on a cross-origin redirect, so
        # the nonstandard `Api-Key` header would ride along to whatever host a 3xx points at. Refuse
        # to follow redirects so the key never leaves api.apitally.io.
        "allow_redirects": False,
    }


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field: str | None = None,
) -> EndpointResource:
    """Builds the top-level (non-fan-out) `Apps` resource. Every other endpoint fans out
    from `Apps` and is built via `build_dependent_resource` in `apitally_source`."""
    config = APITALLY_ENDPOINTS[endpoint]
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

    endpoint_config: Endpoint = {
        "path": config.path,
        "data_selector": "data",
    }
    if config.page_size_param is None:
        endpoint_config["paginator"] = SinglePagePaginator()
    else:
        endpoint_config["params"] = {config.page_size_param: config.page_size}

    use_merge = should_use_incremental_field and bool(config.incremental_fields)
    if use_merge:
        endpoint_config["incremental"] = _incremental_window(
            incremental_field or config.default_incremental_field or config.incremental_fields[0]["field"]
        )

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_merge else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _make_source_response(config: ApitallyEndpointConfig, items_fn: Callable[[], Iterable[Any]]) -> SourceResponse:
    primary_keys = config.primary_key if isinstance(config.primary_key, list) else [config.primary_key]
    return SourceResponse(
        name=config.name,
        items=items_fn,
        primary_keys=primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def apitally_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: Optional[ResumableSourceManager[ApitallyResumeConfig]] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = APITALLY_ENDPOINTS[endpoint]
    client_config = _client_config(api_key)

    if endpoint_config.fanout:
        child_endpoint_extra: Endpoint | None = None
        if endpoint_config.page_size_param is None:
            # Endpoints has no pagination at all — override the client's cursor paginator
            # for this child so it doesn't send an undocumented next_token/limit param.
            child_endpoint_extra = {"paginator": SinglePagePaginator()}

        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=APITALLY_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=endpoint_config.fanout,
                client_config=client_config,
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
                incremental_config_factory=_incremental_window,
                child_endpoint_extra=child_endpoint_extra,
                page_size_param=endpoint_config.page_size_param,
            ),
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field, incremental_field)],
    }

    resource = rest_api_resource(config, team_id, job_id, db_incremental_field_last_value)
    return _make_source_response(endpoint_config, lambda: resource)


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    try:
        # `allow_redirects=False`: keep the `Api-Key` header from being replayed to a redirect
        # target off api.apitally.io. A 3xx then falls through to the error return below.
        response = make_tracked_session(redact_values=(api_key,), allow_redirects=False).get(
            f"{APITALLY_BASE_URL}/v1/apps",
            headers={"Api-Key": api_key, "Accept": "application/json"},
            timeout=10,
        )
    except RequestException as exc:
        return False, str(exc)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Apitally API key."
    if response.status_code == 403:
        return False, "Your Apitally plan does not include API access. Upgrade to the Premium plan to enable it."

    try:
        detail = response.json().get("detail", response.text)
    except Exception:
        detail = response.text
    return False, str(detail)
