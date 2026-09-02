from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from requests.auth import HTTPBasicAuth

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.settings import (
    BASE_URL,
    OPN_PAYMENTS_ENDPOINTS,
    PAGE_SIZE,
    PARTITION_KEY,
)


@frozen
class OpnPaymentsResumeConfig:
    offset: int


def _to_iso8601(value: Any) -> Any:
    """Format a stored watermark as the UTC ISO 8601 string Opn Payments' `from` filter takes."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return value


def validate_credentials(secret_key: str, api_version: str) -> tuple[bool, str | None]:
    """Probe the cheapest authenticated endpoint Opn Payments offers: the single account object."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(headers={"Omise-Version": api_version}, redact_values=(secret_key,)),
        f"{BASE_URL}/account",
        auth=HTTPBasicAuth(secret_key, ""),
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Your Opn Payments secret key is invalid. Check the key and try again."
    if status is None:
        return False, "Could not reach the Opn Payments API."
    return False, f"Opn Payments API returned status {status}."


def opn_payments_source(
    secret_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OpnPaymentsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    api_version: str = "2019-05-29",
) -> SourceResponse:
    endpoint_config = OPN_PAYMENTS_ENDPOINTS[endpoint]

    params: dict[str, Any] = {
        "limit": PAGE_SIZE,
        # Omise defaults list endpoints to chronological order already; pin it explicitly so
        # `SourceResponse.sort_mode="asc"` below always matches the order rows actually arrive in.
        "order": "chronological",
    }
    if should_use_incremental_field:
        params["from"] = {
            "type": "incremental",
            "cursor_path": "created_at",
            "initial_value": "1970-01-01T00:00:00Z",
            "convert": _to_iso8601,
        }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "headers": {"Omise-Version": api_version},
            "auth": {"type": "http_basic", "username": secret_key, "password": ""},
            # `total` (the paginator's default `total_path`) bounds pagination to the
            # (possibly `from`-filtered) matching record count, so a merchant's whole history
            # is never re-walked once the incremental watermark has advanced.
            "paginator": OffsetPaginator(limit=PAGE_SIZE),
        },
        "resources": [
            cast(
                EndpointResource,
                {
                    "name": endpoint,
                    "table_name": endpoint_config.table_name,
                    "write_disposition": {"disposition": "merge", "strategy": "upsert"}
                    if should_use_incremental_field
                    else "replace",
                    "table_format": "delta",
                    "endpoint": {
                        "path": endpoint_config.path,
                        "params": params,
                        "data_selector": "data",
                    },
                },
            )
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; saved AFTER a page is yielded so a crash
        # re-yields (merge dedupes on `id`) rather than skipping a page.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(OpnPaymentsResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[PARTITION_KEY],
    )
