import dataclasses
from collections.abc import AsyncIterable, Callable, Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from products.warehouse_sources.backend.temporal.data_imports.sources.avalara.settings import (
    AVALARA_ENDPOINTS,
    AvalaraEndpointConfig,
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
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# Credentials only work against their own environment — a sandbox license key is rejected by
# production and vice versa.
AVALARA_ENVIRONMENT_HOSTS: dict[str, str] = {
    "production": "https://rest.avatax.com",
    "sandbox": "https://sandbox-rest.avatax.com",
}

# AvaTax's list/query endpoints wrap results as {"@recordsetCount": N, "value": [...], "@nextLink": ...}.
DATA_SELECTOR = "value"
RECORDSET_COUNT_PATH = "@recordsetCount"


@dataclasses.dataclass(frozen=False)
class AvalaraResumeConfig:
    # $skip value for the next page. Only populated for the top-level Companies endpoint — the
    # fan-out children (Transactions, Nexus, Customers, ExemptionCertificates) have no resume hook
    # in the rest_source framework's dependent-resource path, so they restart from the first
    # company on retry; merge write-disposition dedupes any re-fetched rows.
    next_offset: int


def base_url(environment: str) -> str:
    try:
        return AVALARA_ENVIRONMENT_HOSTS[environment]
    except KeyError:
        raise ValueError(f"Unknown Avalara environment: {environment!r}. Use 'production' or 'sandbox'.")


def _format_filter_date(value: Any) -> str:
    """Format an incremental cursor as the quoted ISO 8601 literal AvaTax's `$filter` expects."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _list_paginator(config: AvalaraEndpointConfig) -> OffsetPaginator:
    return OffsetPaginator(
        limit=config.page_size,
        offset_param="$skip",
        limit_param="$top",
        total_path=RECORDSET_COUNT_PATH,
    )


def _client_config(account_id: str, license_key: str, environment: str) -> ClientConfig:
    return {
        "base_url": base_url(environment),
        "headers": {"Accept": "application/json"},
        "auth": {
            "type": "http_basic",
            "username": account_id,
            "password": license_key,
        },
    }


def _build_params(
    field: str, should_use_incremental_field: bool, db_incremental_field_last_value: Any
) -> dict[str, Any]:
    # An explicit $orderBy keeps page boundaries stable on full refresh too (AvaTax's default
    # order is otherwise undocumented), and matches the ascending sort_mode below.
    params: dict[str, Any] = {"$orderBy": f"{field} ASC"}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        params["$filter"] = f"{field} gt '{_format_filter_date(db_incremental_field_last_value)}'"
    return params


def _incremental_config_factory(field: str) -> IncrementalConfig:
    # start_param="$filter" injects a literal OData filter expression rather than a bracketed
    # `field[op]=value` param — AvaTax's $filter takes one combined "field op 'value'" string.
    return {
        "start_param": "$filter",
        "convert": lambda value: f"{field} gt '{_format_filter_date(value)}'",
    }


def get_resource(
    config: AvalaraEndpointConfig,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    field = incremental_field or config.default_incremental_field or "modifiedDate"
    endpoint: Endpoint = {
        "path": config.path,
        "params": _build_params(field, should_use_incremental_field, db_incremental_field_last_value),
        "data_selector": DATA_SELECTOR,
        "paginator": _list_paginator(config),
    }
    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


def _make_source_response(
    config: AvalaraEndpointConfig,
    items_fn: Callable[[], Iterable[Any] | AsyncIterable[Any]],
    column_hints: Optional[dict[str, Any]] = None,
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items_fn,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
        column_hints=column_hints,
    )


def _non_fanout_source(
    account_id: str,
    license_key: str,
    environment: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AvalaraResumeConfig],
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    config = AVALARA_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": _client_config(account_id, license_key, environment),
        "resource_defaults": {},
        "resources": [
            get_resource(config, should_use_incremental_field, incremental_field, db_incremental_field_last_value)
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.next_offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge/replace both tolerate a re-fetch) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(AvalaraResumeConfig(next_offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _make_source_response(config, lambda: resource, column_hints=resource.column_hints)


def _fanout_source(
    account_id: str,
    license_key: str,
    environment: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    config = AVALARA_ENDPOINTS[endpoint]
    assert config.fanout is not None
    parent_config = AVALARA_ENDPOINTS[config.fanout.parent_name]
    field = incremental_field or config.default_incremental_field or "modifiedDate"

    # The parent (Companies) listing must never carry the child's incremental filter — every
    # sync needs the full company list to fan out to, regardless of which transactions changed.
    fanout = dataclasses.replace(config.fanout, child_params={"$orderBy": f"{field} ASC"})

    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=AVALARA_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=fanout,
            client_config=_client_config(account_id, license_key, environment),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=field,
            incremental_config_factory=_incremental_config_factory,
            page_size_param="$top",
            parent_endpoint_extra={
                "paginator": _list_paginator(parent_config),
                "data_selector": DATA_SELECTOR,
            },
            child_endpoint_extra={
                "paginator": _list_paginator(config),
                "data_selector": DATA_SELECTOR,
            },
        ),
    )

    return _make_source_response(config, lambda: dependent_resource)


def avalara_source(
    account_id: str,
    license_key: str,
    environment: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AvalaraResumeConfig],
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = AVALARA_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(
            account_id,
            license_key,
            environment,
            endpoint,
            team_id,
            job_id,
            should_use_incremental_field,
            incremental_field,
            db_incremental_field_last_value,
        )

    return _non_fanout_source(
        account_id,
        license_key,
        environment,
        endpoint,
        team_id,
        job_id,
        resumable_source_manager,
        should_use_incremental_field,
        incremental_field,
        db_incremental_field_last_value,
    )


def validate_credentials(account_id: str, license_key: str, environment: str) -> tuple[bool, str | None]:
    """Probe AvaTax's Ping utility, the cheapest call that reports whether credentials are valid.

    Ping itself needs no auth to reach, but its ``authenticated`` field reflects whatever Basic
    auth was supplied, so a 200 with ``authenticated: false`` still means bad credentials.
    """
    try:
        url = f"{base_url(environment)}/api/v2/utilities/ping"
    except ValueError as exc:
        return False, str(exc)

    try:
        response = make_tracked_session(redact_values=(license_key,)).get(
            url,
            auth=(account_id, license_key),
            headers={"Accept": "application/json"},
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001 — a credential probe must never raise
        return False, f"Could not reach Avalara AvaTax: {exc}"

    if response.status_code != 200:
        return False, f"Avalara AvaTax returned an unexpected response (HTTP {response.status_code})."

    if not response.json().get("authenticated"):
        return False, "Avalara authentication failed. Check your account ID and license key."

    return True, None
