import dataclasses
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.settings import (
    API_BASE_URL,
    ENDPOINT_CONFIGS,
    PAGE_SIZE,
    RazorpayEndpointConfig,
)

# Razorpay has no updated-at filter, so incremental syncs window on created_at only. Re-read a
# trailing overlap each run to catch status transitions on recently created records (e.g.
# authorized -> captured payments, settlement state changes); the merge on `id` dedupes the
# overlap. Older mutations still need an occasional full refresh.
INCREMENTAL_LOOKBACK_SECONDS = 3 * 24 * 60 * 60

# The API rejects `from` values before 2000-01-01 with a 400.
MIN_FROM_TIMESTAMP = 946_684_800

# The recon report has no "all months" query, so a full sync walks every month from before
# Razorpay's launch to now. Months are settlement months on Razorpay's IST calendar.
RECON_FIRST_MONTH = (2014, 1)
RECON_TIMEZONE = ZoneInfo("Asia/Kolkata")


MISSING_ACCOUNT_NUMBER_ERROR = (
    "Add your RazorpayX account number to the Razorpay source settings to sync RazorpayX transactions."
)


@dataclasses.dataclass(frozen=True)
class RazorpayResumeConfig:
    skip: int
    # Set only for the settlement recon report: the month that `skip` applies to.
    recon_year: Optional[int] = None
    recon_month: Optional[int] = None


def build_from_param(db_incremental_field_last_value: Optional[Any]) -> Optional[int]:
    """UNIX-seconds `from` bound for an incremental sync, or None for a full walk."""
    if db_incremental_field_last_value is None:
        return None

    try:
        watermark = int(db_incremental_field_last_value)
    except (TypeError, ValueError):
        return None

    return max(watermark - INCREMENTAL_LOOKBACK_SECONDS, MIN_FROM_TIMESTAMP)


def _build_paginator(config: RazorpayEndpointConfig) -> BasePaginator:
    if not config.paginated:
        return SinglePagePaginator()

    # Collection responses carry `count` as the page's item count (not a grand total), so
    # termination is a short or empty page; `total_path=None` keeps the paginator from
    # misreading any body field as a total.
    return OffsetPaginator(
        limit=PAGE_SIZE,
        offset_param="skip",
        limit_param="count",
        total_path=None,
    )


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    account_number: Optional[str] = None,
) -> EndpointResource:
    config = ENDPOINT_CONFIGS[name]

    params: dict[str, Any] = {}
    if config.requires_account_number:
        params["account_number"] = account_number
    if config.supports_created_filter and should_use_incremental_field:
        # None values are dropped before the request, so the first incremental sync (no
        # watermark yet) walks the full history without a `from` bound.
        params["from"] = build_from_param(db_incremental_field_last_value)

    return {
        "name": config.name,
        "table_name": config.name.lower(),
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "data_selector": config.data_selector,
            "path": config.path,
            "params": params,
            "paginator": _build_paginator(config),
        },
        "table_format": "delta",
    }


def _recon_month(timestamp: float) -> tuple[int, int]:
    moment = datetime.fromtimestamp(timestamp, tz=RECON_TIMEZONE)
    return moment.year, moment.month


def _current_recon_month() -> tuple[int, int]:
    return _recon_month(datetime.now(tz=RECON_TIMEZONE).timestamp())


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def recon_start_month(db_incremental_field_last_value: Optional[Any]) -> tuple[int, int]:
    from_timestamp = build_from_param(db_incremental_field_last_value)
    if from_timestamp is None:
        return RECON_FIRST_MONTH
    return max(_recon_month(from_timestamp), RECON_FIRST_MONTH)


def _iter_settlement_recon(
    key_id: str,
    key_secret: str,
    config: RazorpayEndpointConfig,
    resumable_source_manager: ResumableSourceManager[RazorpayResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[list[dict[str, Any]]]:
    year, month = recon_start_month(db_incremental_field_last_value)
    skip = 0
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.recon_year is not None and resume.recon_month is not None:
        year, month, skip = resume.recon_year, resume.recon_month, resume.skip

    end = _current_recon_month()
    client = RESTClient(
        base_url=API_BASE_URL,
        auth=HttpBasicAuth(username=key_id, password=key_secret),
        paginator=SinglePagePaginator(),
    )

    try:
        while (year, month) <= end:
            params = {"year": year, "month": month, "count": PAGE_SIZE, "skip": skip}
            page = next(client.paginate(config.path, params=params, data_selector=config.data_selector), [])
            rows = [row for row in page if isinstance(row, dict)]

            if len(page) < PAGE_SIZE:
                year, month = _next_month(year, month)
                skip = 0
            else:
                skip += len(page)

            resumable_source_manager.save_state(RazorpayResumeConfig(skip=skip, recon_year=year, recon_month=month))
            if rows:
                yield rows
            else:
                resumable_source_manager.safe_point()
    finally:
        client.session.close()


def razorpay_source(
    key_id: str,
    key_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RazorpayResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
    account_number: Optional[str] = None,
) -> SourceResponse:
    endpoint_config = ENDPOINT_CONFIGS[endpoint]
    if endpoint_config.requires_account_number and not account_number:
        raise ValueError(MISSING_ACCOUNT_NUMBER_ERROR)

    if not should_use_incremental_field:
        db_incremental_field_last_value = None

    if endpoint_config.monthly_recon:
        return SourceResponse(
            name=endpoint_config.name,
            items=lambda: _iter_settlement_recon(
                key_id, key_secret, endpoint_config, resumable_source_manager, db_incremental_field_last_value
            ),
            primary_keys=list(endpoint_config.primary_keys),
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="week",
            partition_keys=[endpoint_config.partition_key],
            # Months are read oldest first, but the order of rows within a month is undocumented.
            sort_mode=None,
        )

    config: RESTAPIConfig = {
        "client": {
            "base_url": API_BASE_URL,
            "auth": {
                "type": "http_basic",
                "username": key_id,
                "password": key_secret,
            },
        },
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [
            get_resource(
                endpoint,
                should_use_incremental_field,
                db_incremental_field_last_value,
                account_number,
            )
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"offset": resume_config.skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles
        # cleanup on completion.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(RazorpayResumeConfig(skip=int(state["offset"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return SourceResponse(
        name=resource.name,
        items=lambda: resource,
        primary_keys=list(endpoint_config.primary_keys),
        column_hints=resource.column_hints,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[endpoint_config.partition_key],
        # List endpoints return newest-first and expose no sort param.
        sort_mode="desc",
    )


def validate_credentials(key_id: str, key_secret: str) -> bool:
    session = make_tracked_session(redact_values=(key_secret,))
    res = session.get(
        f"{API_BASE_URL}/v1/payments",
        params={"count": 1},
        auth=(key_id, key_secret),
        timeout=30,
    )
    return res.status_code == 200
