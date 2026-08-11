import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    BearerTokenAuthConfig,
    ResponseAction,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.settings import FLUTTERWAVE_ENDPOINTS

FLUTTERWAVE_API_HOST = "https://api.flutterwave.com"

# Floor of the mandatory date window on /transactions. Flutterwave has no merchant records that
# predate the platform, so this pulls the full history on every sync without having to guess when the
# account was opened.
EARLIEST_WINDOW_START = "2016-01-01"

# The API's `from`/`to` window is day-granular and Flutterwave does not expose the account's
# reporting timezone, so the window end is padded by a day rather than pinned to UTC today. Pinning
# it would clip records booked "today" in a timezone ahead of UTC.
WINDOW_END_PADDING_DAYS = 1

# v3 answers "no records in this range" on some list endpoints with HTTP 400 rather than an empty
# `data` array, so those bodies are treated as an empty page instead of failing the sync. The match
# is deliberately narrow: a genuine parameter error ("page parameter must be a positive integer")
# does not carry this wording and still raises. Both cases are listed because the substring match is
# case sensitive and v3 is inconsistent about capitalizing "found".
_NO_RECORDS_RESPONSE_ACTIONS: list[ResponseAction] = [
    {"status_code": 400, "content": "found", "action": "ignore"},
    {"status_code": 400, "content": "Found", "action": "ignore"},
]


@dataclasses.dataclass
class FlutterwaveResumeConfig:
    # 1-based page number to resume pagination from. 1 means "start from the beginning".
    next_page: int = 1


def base_url(api_version: str) -> str:
    return f"{FLUTTERWAVE_API_HOST}/{api_version}"


def _auth_config(secret_key: str) -> BearerTokenAuthConfig:
    return {"type": "bearer", "token": secret_key}


def _window_end() -> str:
    return (datetime.now(UTC).date() + timedelta(days=WINDOW_END_PADDING_DAYS)).isoformat()


def validate_credentials(secret_key: str, api_version: str) -> tuple[bool, str | None]:
    # /subaccounts is the cheapest authenticated probe: no required params, a small body, and it only
    # needs the account's secret key. Its response also carries subaccount bank details, so keep it
    # out of the HTTP diagnostic sample store (capture=False).
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(secret_key,), capture=False),
        f"{base_url(api_version)}/subaccounts",
        headers={"Authorization": f"Bearer {secret_key}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Flutterwave secret key. Check the key in your Flutterwave dashboard and try again."
    if status == 400:
        # The key was accepted; v3 uses 400 for "no subaccounts on this account", which is not a
        # credential problem.
        return True, None
    return False, "Could not reach the Flutterwave API. Try again in a few minutes."


def get_rows(
    secret_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[FlutterwaveResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = FLUTTERWAVE_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    if config.requires_date_window:
        # /transactions requires `from`/`to`, so a full refresh sends the whole history window: the
        # earliest-possible floor through today (padded a day for timezones ahead of UTC).
        params["from"] = EARLIEST_WINDOW_START
        params["to"] = _window_end()

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
        "data_selector": "data",
        # Every v3 list endpoint is page-numbered from 1 and reports the page count under
        # `meta.page_info.total_pages`, which stops pagination without paying an extra empty page.
        # Page size is left to the API: v3 documents no maximum, and an over-cap value 4xxs.
        "paginator": PageNumberPaginator(base_page=1, total_path="meta.page_info.total_pages"),
        "response_actions": _NO_RECORDS_RESPONSE_ACTIONS,
    }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(api_version),
            "headers": {"Accept": "application/json"},
            "auth": _auth_config(secret_key),
            # These bodies carry bank account numbers and transaction metadata, so keep them out of
            # the HTTP diagnostic sample store (requests are still metered and logged).
            "session": make_tracked_session(redact_values=(secret_key,), capture=False),
        },
        "resources": [{"name": endpoint, "endpoint": endpoint_config}],
    }

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.next_page > 1:
        initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework calls this AFTER a page is yielded and only while a next page remains, so a
        # crash re-yields the next page rather than skipping it (the merge dedupes on primary key).
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(FlutterwaveResumeConfig(next_page=int(state["page"])))

    yield from rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def flutterwave_source(
    secret_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[FlutterwaveResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = FLUTTERWAVE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            secret_key=secret_key,
            endpoint=endpoint,
            team_id=team_id,
            job_id=job_id,
            api_version=api_version,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
