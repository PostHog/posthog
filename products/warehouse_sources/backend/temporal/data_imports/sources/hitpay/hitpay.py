from collections.abc import Iterable
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.settings import (
    HITPAY_ENDPOINTS,
    RECURRING_BILLING_STATUSES,
    HitpayEndpointConfig,
)

HITPAY_PRODUCTION_BASE_URL = "https://api.hit-pay.com"
HITPAY_SANDBOX_BASE_URL = "https://api.sandbox.hit-pay.com"


@frozen
class HitpayResumeConfig:
    """Paginator checkpoint. Only one of the two is ever set, matching the endpoint's pagination
    kind (page-number for most endpoints, cursor for Charges)."""

    next_page: Optional[int] = None
    next_cursor: Optional[str] = None


def base_url_for_environment(environment: Optional[str]) -> str:
    return HITPAY_SANDBOX_BASE_URL if environment == "sandbox" else HITPAY_PRODUCTION_BASE_URL


def _extra_headers(platform_api_key: Optional[str]) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if platform_api_key:
        headers["X-PLATFORM-KEY"] = platform_api_key
    return headers


def _redact_values(api_key: str, platform_api_key: Optional[str]) -> tuple[str, ...]:
    return tuple(value for value in (api_key, platform_api_key) if value)


def _format_charge_date(value: Any) -> str:
    """Format the incremental watermark for Charges' `date_from` filter (YYYY-MM-DD, day granularity).

    Truncating to the day rounds the lower bound down, so a resumed sync re-reads the watermark
    day rather than skipping charges created later on it. The merge upsert dedupes the overlap.
    """
    normalized = coerce_datetime_to_utc(value)
    if normalized is None:
        return str(value)
    return normalized.strftime("%Y-%m-%d")


def _incremental_param(cursor_path: str) -> dict[str, Any]:
    return {
        "type": "incremental",
        "cursor_path": cursor_path,
        "initial_value": "1970-01-01",
        "convert": _format_charge_date,
    }


def _paginator_for(config: HitpayEndpointConfig) -> BasePaginator:
    if config.pagination == "cursor":
        return JSONResponseCursorPaginator(cursor_path="meta.next_cursor", cursor_param="cursor")
    if config.pagination == "page":
        return PageNumberPaginator(base_page=1, page_param=config.page_param, total_path="meta.last_page")
    return SinglePagePaginator()


def get_resource(endpoint: str, should_use_incremental_field: bool) -> EndpointResource:
    config = HITPAY_ENDPOINTS[endpoint]
    is_incremental = bool(config.incremental_fields) and should_use_incremental_field

    params: dict[str, Any] = {}
    if is_incremental:
        params["date_from"] = _incremental_param("created_at")

    return {
        "name": endpoint,
        "table_name": config.table_name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        "endpoint": {
            "data_selector": "data",
            "path": config.path,
            "params": params,
            "paginator": _paginator_for(config),
        },
        "table_format": "delta",
    }


def _client_config(api_key: str, platform_api_key: Optional[str], environment: Optional[str]) -> ClientConfig:
    return {
        "base_url": base_url_for_environment(environment),
        "headers": _extra_headers(platform_api_key),
        "auth": APIKeyAuth(api_key=api_key, name="X-BUSINESS-API-KEY", location="header"),
        # Built explicitly (rather than left to RESTClient's default) so the optional
        # X-PLATFORM-KEY header value is also redacted from logged/sampled requests — the
        # framework auth object only knows about the business API key.
        "session": make_tracked_session(redact_values=_redact_values(api_key, platform_api_key)),
        # X-BUSINESS-API-KEY/X-PLATFORM-KEY are custom headers; `requests` doesn't strip them on
        # a cross-origin redirect, so refuse to follow one rather than replay the keys elsewhere.
        "allow_redirects": False,
    }


def _recurring_billing_source(
    api_key: str,
    platform_api_key: Optional[str],
    environment: Optional[str],
) -> SourceResponse:
    config = HITPAY_ENDPOINTS["RecurringBilling"]
    client = RESTClient(
        base_url=base_url_for_environment(environment),
        headers=_extra_headers(platform_api_key),
        auth=APIKeyAuth(api_key=api_key, name="X-BUSINESS-API-KEY", location="header"),
        session=make_tracked_session(redact_values=_redact_values(api_key, platform_api_key)),
        allow_redirects=False,
    )

    def iterate_all_statuses() -> Iterable[list[dict[str, Any]]]:
        for status in RECURRING_BILLING_STATUSES:
            for page in client.paginate(
                path=config.path,
                params={"status": status},
                paginator=SinglePagePaginator(),
                data_selector="data",
            ):
                if page:
                    yield page

    return SourceResponse(
        name="RecurringBilling",
        items=iterate_all_statuses,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def hitpay_source(
    api_key: str,
    platform_api_key: Optional[str],
    environment: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HitpayResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    if endpoint == "RecurringBilling":
        return _recurring_billing_source(api_key, platform_api_key, environment)

    config = HITPAY_ENDPOINTS[endpoint]
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, platform_api_key, environment),
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if resume.next_page is not None:
                initial_paginator_state = {"page": resume.next_page}
            elif resume.next_cursor is not None:
                initial_paginator_state = {"cursor": resume.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if not state:
            return
        if state.get("page") is not None:
            resumable_source_manager.save_state(HitpayResumeConfig(next_page=int(state["page"])))
        elif state.get("cursor") is not None:
            resumable_source_manager.save_state(HitpayResumeConfig(next_cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
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
        column_hints=resource.column_hints,
    )


def validate_credentials(
    api_key: str, platform_api_key: Optional[str], environment: Optional[str]
) -> tuple[bool, str | None]:
    headers = {"X-BUSINESS-API-KEY": api_key, **_extra_headers(platform_api_key)}
    is_valid, status_code = validate_via_probe(
        lambda: make_tracked_session(redact_values=_redact_values(api_key, platform_api_key)),
        f"{base_url_for_environment(environment)}/v1/account-status",
        headers=headers,
        # X-BUSINESS-API-KEY is a custom header; `requests` doesn't strip non-Authorization
        # headers on a cross-origin redirect, so refuse to follow one.
        allow_redirects=False,
    )
    if is_valid:
        return True, None
    if status_code == 401:
        return False, "Invalid HitPay API key. Check the key in your HitPay dashboard and try again."
    return False, "Could not connect to HitPay with the provided API key."
