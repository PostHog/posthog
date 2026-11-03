import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.autumn.settings import (
    AUTUMN_API_VERSION_2_4_0,
    AUTUMN_BASE_URL,
    AUTUMN_ENDPOINTS,
    AUTUMN_V2_4_MAX_PAGE_SIZE,
    PARTITION_BUCKET_MILLISECONDS,
    AutumnEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionMode,
    SourceResponse,
)


@dataclasses.dataclass(frozen=True)
class AutumnResumeConfig:
    next_cursor: str | None = None
    # Customer fan-out tables resume inside a customers page: next_cursor is then the cursor that
    # fetched that page (None for the first page) and last_customer_id the last customer done on it.
    last_customer_id: str | None = None


def _watermark_to_epoch_ms(value: Any) -> int:
    """Coerce the persisted incremental watermark to epoch milliseconds."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    return int(value)


def _make_paginator(config: AutumnEndpointConfig) -> BasePaginator:
    if config.paginated:
        return JSONResponseCursorPaginator(
            cursor_path="next_cursor",
            cursor_param="start_cursor",
            param_location="json",
        )
    return SinglePagePaginator()


def _page_size(config: AutumnEndpointConfig, api_version: str) -> int:
    if api_version == AUTUMN_API_VERSION_2_4_0:
        return min(config.page_size, AUTUMN_V2_4_MAX_PAGE_SIZE)
    return config.page_size


def _build_request_body(
    config: AutumnEndpointConfig,
    api_version: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Optional[Any],
) -> dict[str, Any]:
    # Single-page endpoints document an optional (or absent) request body; an empty JSON
    # object is accepted either way and keeps the request shape uniform.
    body: dict[str, Any] = {}
    if config.paginated:
        body["limit"] = _page_size(config, api_version)
    if (
        config.incremental_range_field is not None
        and should_use_incremental_field
        and incremental_field == config.incremental_range_field
        and db_incremental_field_last_value is not None
    ):
        # The docs don't state whether custom_range.start is inclusive; starting exactly at
        # the watermark may re-fetch boundary rows, which the merge on primary key dedupes.
        body["custom_range"] = {"start": _watermark_to_epoch_ms(db_incremental_field_last_value)}
    return body


def _post(client: RESTClient, path: str, body: dict[str, Any]) -> dict[str, Any]:
    pages = list(client.paginate(path=path, method="POST", json=body, data_selector="$"))
    response = pages[0][0] if pages and pages[0] else None
    if not isinstance(response, dict):
        raise ValueError(f"Autumn returned an unexpected response from {path}. Expected a JSON object.")
    return response


def _iter_customer_fan_out(
    api_key: str,
    config: AutumnEndpointConfig,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[AutumnResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    customers = AUTUMN_ENDPOINTS["Customers"]
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.next_cursor if resume is not None else None
    done_through = resume.last_customer_id if resume is not None else None
    client = RESTClient(
        base_url=AUTUMN_BASE_URL,
        auth=BearerTokenAuth(token=api_key),
        headers={"x-api-version": api_version},
        paginator=SinglePagePaginator(),
    )

    try:
        while True:
            body: dict[str, Any] = {"limit": _page_size(customers, api_version)}
            if cursor is not None:
                body["start_cursor"] = cursor
            page = _post(client, customers.path, body)
            page_customers = page.get("list") or []

            start = 0
            # Resume after the last finished customer by id, not position: a customer deleted since
            # the checkpoint would shift positions and skip one. If that customer is gone, replay the page.
            if done_through is not None:
                ids = [customer.get("id") for customer in page_customers]
                if done_through in ids:
                    start = ids.index(done_through) + 1
                done_through = None

            for customer in page_customers[start:]:
                customer_id = customer.get("id")
                # Customers created without an id can't be passed to a customer-scoped endpoint.
                if customer_id is None:
                    resumable_source_manager.safe_point()
                    continue
                child = _post(client, config.path, {"customer_id": customer_id})
                rows = [{**row, "customer_id": customer_id} for row in child.get(config.data_selector) or []]
                resumable_source_manager.save_state(
                    AutumnResumeConfig(next_cursor=cursor, last_customer_id=str(customer_id))
                )
                if rows:
                    yield rows
                else:
                    resumable_source_manager.safe_point()

            next_cursor = page.get("next_cursor")
            if not next_cursor:
                break
            if next_cursor == cursor:
                raise ValueError("Autumn customers.list pagination is not advancing (repeated cursor)")
            cursor = next_cursor
            resumable_source_manager.safe_point()
    finally:
        client.session.close()


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    json_body: dict[str, Any],
) -> EndpointResource:
    config = AUTUMN_ENDPOINTS[endpoint]

    endpoint_config: Endpoint = {
        "method": "POST",
        "path": config.path,
        "json": json_body,
        "data_selector": config.data_selector,
        "paginator": _make_paginator(config),
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def autumn_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[AutumnResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = AUTUMN_ENDPOINTS[endpoint]

    if config.customer_fan_out:
        return SourceResponse(
            name=config.name,
            items=lambda: _iter_customer_fan_out(api_key, config, api_version, resumable_source_manager),
            primary_keys=config.primary_keys,
        )

    json_body = _build_request_body(
        config,
        api_version,
        should_use_incremental_field,
        incremental_field,
        db_incremental_field_last_value,
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": AUTUMN_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {"x-api-version": api_version},
        },
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field, json_body)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles
        # cleanup on completion.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(AutumnResumeConfig(next_cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # Incremental filtering rides the custom_range body param above, not the
        # framework's query-param incremental machinery.
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partition_keys: Optional[list[str]] = None
    partition_mode: Optional[PartitionMode] = None
    partition_size: Optional[int] = None
    if config.partition_key is not None:
        partition_keys = [config.partition_key]
        partition_mode = "numerical"
        partition_size = PARTITION_BUCKET_MILLISECONDS

    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_keys=partition_keys,
        partition_mode=partition_mode,
        partition_size=partition_size,
        # The docs don't state list ordering; usage-event logs are typically newest-first,
        # and "desc" is also the safe choice if the order turns out to be ascending — the
        # watermark then only commits once the sync completes.
        sort_mode="desc" if config.incremental_range_field is not None else "asc",
    )


def validate_credentials(api_key: str, api_version: str) -> tuple[bool, str | None]:
    session = make_tracked_session(redact_values=(api_key,))
    response = session.post(
        f"{AUTUMN_BASE_URL}/v1/customers.list",
        headers={
            "Authorization": f"Bearer {api_key}",
            "x-api-version": api_version,
        },
        json={"limit": 1},
        timeout=30,
    )
    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, (
            "Autumn rejected the secret key. Check that you copied a secret key (am_sk_...) "
            "for the environment you want to sync."
        )
    return False, f"Autumn returned an unexpected status ({response.status_code})"
