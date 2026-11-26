from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.sources.opn_payments.settings import (
    BASE_URL,
    OPN_PAYMENTS_ENDPOINTS,
    PAGE_SIZE,
    PARTITION_KEY,
)
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    EndpointResource,
    OffsetPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SortMode,
    SourceResponse,
    build_dependent_resource,
    frozen,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)


@frozen
class OpnPaymentsResumeConfig:
    offset: int | None = None
    # Paginator state of a fan-out child (parent page plus the child offset within it).
    fanout_state: dict[str, Any] | None = None


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


def _client_config(secret_key: str, api_version: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "headers": {"Omise-Version": api_version},
        "auth": {"type": "http_basic", "username": secret_key, "password": ""},
        # `total` (the paginator's default `total_path`) bounds pagination to the
        # (possibly `from`-filtered) matching record count, so a merchant's whole history
        # is never re-walked once the incremental watermark has advanced.
        "paginator": OffsetPaginator(limit=PAGE_SIZE),
    }


def _fanout_resource(
    secret_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OpnPaymentsResumeConfig],
    api_version: str,
) -> Iterable[Any]:
    fanout = OPN_PAYMENTS_ENDPOINTS[endpoint].fanout
    assert fanout is not None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(OpnPaymentsResumeConfig(fanout_state=state))

    return build_dependent_resource(
        endpoint_configs=OPN_PAYMENTS_ENDPOINTS,
        child_endpoint=endpoint,
        fanout=fanout,
        client_config=_client_config(secret_key, api_version),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        parent_endpoint_extra={"data_selector": "data"},
        child_endpoint_extra={"data_selector": "data"},
        resume_hook=save_checkpoint,
        initial_paginator_state=resume.fanout_state if resume else None,
        resume_parent_pagination=True,
    )


def _top_level_resource(
    secret_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OpnPaymentsResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    api_version: str,
) -> Iterable[Any]:
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
        "client": _client_config(secret_key, api_version),
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
        if resume is not None and resume.offset is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; saved AFTER a page is yielded so a crash
        # re-yields (merge dedupes on `id`) rather than skipping a page.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(OpnPaymentsResumeConfig(offset=int(state["offset"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


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
    sort_mode: SortMode | None

    if endpoint_config.fanout is not None:
        resource = _fanout_resource(secret_key, endpoint, team_id, job_id, resumable_source_manager, api_version)
        sort_mode = None
    else:
        resource = _top_level_resource(
            secret_key,
            endpoint,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
            api_version,
        )
        sort_mode = "asc"

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(endpoint_config.primary_keys),
        sort_mode=sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[PARTITION_KEY],
    )
