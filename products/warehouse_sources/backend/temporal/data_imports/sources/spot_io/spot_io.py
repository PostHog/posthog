import dataclasses
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, cast

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.settings import (
    DEFAULT_COST_LOOKBACK_DAYS,
    SPOT_IO_BASE_URL,
    SPOT_IO_ENDPOINTS,
    SpotIoEndpointConfig,
)

# Spot's response envelope wraps every list under `response.items`, regardless of endpoint.
DATA_SELECTOR = "response.items"


@dataclasses.dataclass
class SpotIoResumeConfig:
    # Opaque framework checkpoint (fan-out resume state for `elastigroup_costs`; the entity
    # list endpoints have no pagination and are never resumed).
    paginator_state: dict[str, Any]


def _format_time_value(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _cost_window_start() -> str:
    return _format_time_value(datetime.now(UTC) - timedelta(days=DEFAULT_COST_LOOKBACK_DAYS))


def _cost_window_end() -> str:
    return _format_time_value(datetime.now(UTC))


def _account_params(account_id: Optional[str]) -> dict[str, Any]:
    return {"accountId": account_id} if account_id else {}


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": SPOT_IO_BASE_URL,
        "auth": {"type": "bearer", "token": api_token},
        "headers": {"Accept": "application/json"},
        "paginator": SinglePagePaginator(),
    }


def validate_credentials(api_token: str, account_id: Optional[str] = None) -> tuple[bool, str | None]:
    # Listing Elastigroups is the cheapest authenticated call available (no required params,
    # and an empty group list is still a valid 200), so it doubles as the credential probe.
    res = make_tracked_session(redact_values=(api_token,)).get(
        f"{SPOT_IO_BASE_URL}/aws/ec2/group",
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
        params=_account_params(account_id),
        timeout=10,
    )
    if res.status_code == 200:
        return True, None
    if res.status_code == 401:
        return False, "Invalid or expired Spot by Flexera API token"
    if res.status_code == 403:
        return False, "Spot by Flexera API token does not have the required permissions"
    return False, f"Spot by Flexera API returned an unexpected status: {res.status_code}"


def get_resource(endpoint: str, account_id: Optional[str] = None) -> EndpointResource:
    config = SPOT_IO_ENDPOINTS[endpoint]
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

    endpoint_config: Endpoint = {
        "path": config.path,
        "data_selector": DATA_SELECTOR,
        "paginator": SinglePagePaginator(),
        "params": _account_params(account_id),
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _make_source_response(endpoint_config: SpotIoEndpointConfig, items_fn: Any) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=endpoint_config.primary_key
        if isinstance(endpoint_config.primary_key, list)
        else [endpoint_config.primary_key],
        sort_mode=endpoint_config.sort_mode,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def spot_io_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SpotIoResumeConfig],
    account_id: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = SPOT_IO_ENDPOINTS[endpoint]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = resume_config.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's somewhere to resume to; the Redis TTL handles cleanup.
        if state:
            resumable_source_manager.save_state(SpotIoResumeConfig(paginator_state=dict(state)))

    if endpoint_config.fanout:
        # `costs/detailed` requires fromDate/toDate on every request and its rows carry no
        # per-row timestamp to track a real watermark from, so this is always a fixed rolling
        # window rather than an incremental cursor (see settings.py).
        child_params_extra: dict[str, Any] = {
            "fromDate": _cost_window_start(),
            "toDate": _cost_window_end(),
            **_account_params(account_id),
        }
        parent_fanout = dataclasses.replace(endpoint_config.fanout, parent_params=_account_params(account_id))

        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=SPOT_IO_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=parent_fanout,
                client_config=_client_config(api_token),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
                page_size_param=None,
                parent_endpoint_extra={"paginator": SinglePagePaginator(), "data_selector": DATA_SELECTOR},
                child_endpoint_extra={"paginator": SinglePagePaginator(), "data_selector": DATA_SELECTOR},
                child_params_extra=child_params_extra,
                resume_hook=save_checkpoint,
                initial_paginator_state=initial_paginator_state,
            ),
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(endpoint=endpoint, account_id=account_id)],
    }

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _make_source_response(endpoint_config, lambda: resource)
