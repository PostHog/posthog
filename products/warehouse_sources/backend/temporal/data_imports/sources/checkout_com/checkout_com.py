import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import OAuth2Auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

CHECKOUT_HOSTS = {
    "production": {"api": "https://api.checkout.com", "auth": "https://access.checkout.com/connect/token"},
    "sandbox": {
        "api": "https://api.sandbox.checkout.com",
        "auth": "https://access.sandbox.checkout.com/connect/token",
    },
}
# Disputes list pages cap at 250.
PAGE_SIZE = 250

# Checkout.com has no list-all-payments endpoint — bulk payment data only
# exists via report files. Disputes are the one honest list surface.
ENDPOINTS = ("disputes",)


@dataclasses.dataclass
class CheckoutComResumeConfig:
    # Disputes paginate with limit/skip; static params are rebuilt from job
    # inputs on resume.
    skip: int


def _hosts(environment: str) -> dict[str, str]:
    hosts = CHECKOUT_HOSTS.get(environment)
    if hosts is None:
        raise ValueError(f"Invalid Checkout.com environment: {environment}")
    return hosts


def _make_auth(environment: str, client_id: str, client_secret: str) -> OAuth2Auth:
    # Checkout.com's token endpoint takes the client credentials as HTTP Basic
    # auth; tokens last ~1h and the framework re-mints on expiry mid-run.
    return OAuth2Auth(
        token_url=_hosts(environment)["auth"],
        client_id=client_id,
        client_secret=client_secret,
        grant_type="client_credentials",
        client_auth_method="basic",
    )


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor for the disputes `from` filter (ISO 8601 UTC)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def validate_credentials(environment: str, client_id: str, client_secret: str) -> bool:
    """Confirm the API credentials are valid by minting a token and probing disputes."""
    try:
        hosts = _hosts(environment)
        auth = _make_auth(environment, client_id, client_secret)
    except ValueError:
        return False
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(client_secret,)),
        f"{hosts['api']}/disputes?limit=1",
        auth=auth,
        # 403 means the token minted (keys are valid) but lacks the disputes
        # scope — accept at create time, like the mint-only check did; the
        # sync-time non-retryable copy guides the scope fix.
        ok_statuses=(200, 403),
    )
    return ok


def checkout_com_source(
    environment: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CheckoutComResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # `from` filters on a dispute's last_update timestamp.
        params["from"] = _format_timestamp(db_incremental_field_last_value)

    config: RESTAPIConfig = {
        "client": {
            "base_url": _hosts(environment)["api"],
            "auth": _make_auth(environment, client_id, client_secret),
            # Disputes paginate with limit/skip and report a grand total_count.
            "paginator": OffsetPaginator(limit=PAGE_SIZE, offset_param="skip", total_path="total_count"),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": endpoint,
                    "params": params,
                    # A missing `data` key means no rows (the pre-framework code
                    # treated it as end-of-list), so the selector is not required.
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; saved AFTER the page is yielded
        # so a crash re-yields the last page (merge dedupes on primary key)
        # rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(CheckoutComResumeConfig(skip=int(state["offset"])))

    resource = rest_api_resource(
        config,
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
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["received_on"],
        # Disputes are returned newest-first; the pipeline commits desc
        # watermarks only when a run completes.
        sort_mode="desc",
        column_hints=resource.column_hints,
    )
