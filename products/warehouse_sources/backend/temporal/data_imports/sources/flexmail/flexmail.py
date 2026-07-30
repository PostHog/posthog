"""Flexmail transport layer.

Flexmail is an email marketing platform. Auth is HTTP Basic (account ID as username, personal
access token as password). Every resource lives under ``https://api.flexmail.eu``.

Responses follow HAL: collection rows live under ``_embedded.item`` (omitted entirely for an empty
collection, so a missing selector legitimately means zero rows) and every row carries navigation
``_links`` that are noise, not data. List endpoints paginate with ``limit``/``offset`` and carry a
top-level ``total``; the segments, opt-in forms and custom fields collections return their whole
result set in one response.

Every table is full refresh only — no list endpoint exposes a server-side timestamp filter, so there
is no incremental cursor to advance.

Built on the shared ``rest_source`` framework: framework ``http_basic`` auth carries the credentials
(and redacts the token from errors/logs), a built-in ``OffsetPaginator`` reproduces the
``limit``/``offset`` + ``total`` termination with resume, and a ``data_map`` strips each row's
``_links``.
"""

import dataclasses
from typing import Any, Optional

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.settings import FLEXMAIL_ENDPOINTS

FLEXMAIL_BASE_URL = "https://api.flexmail.eu"
# List endpoints accept a `limit` of up to 500; the largest page minimises round trips against the
# 60 requests/minute rate limit.
PAGE_SIZE = 500
# Cheap list endpoint used to confirm the credentials are genuine. Personal access tokens are
# account-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/sources"

# HAL collection rows live here; omitted for an empty collection, so a missing selector is a legit
# zero-row page (not an error — no data_selector_required).
_DATA_SELECTOR = "_embedded.item"


@dataclasses.dataclass
class FlexmailResumeConfig:
    # Offset of the next page to fetch. Flexmail paginates with `limit`/`offset` query params, so a
    # crashed full-refresh sync resumes from the page after the last one yielded; merge dedupes the
    # re-pulled page on `id`. `0` means start from the first page.
    offset: int = 0


def _strip_links(item: dict[str, Any]) -> dict[str, Any]:
    # Per-item `_links` are HAL navigation, not data.
    return {k: v for k, v in item.items() if k != "_links"}


def _client_config(account_id: str, personal_access_token: str) -> ClientConfig:
    # HTTP Basic auth is supplied via the framework auth config so the token is redacted from logs and
    # raised error messages; only the non-secret Accept header is set here.
    return {
        "base_url": FLEXMAIL_BASE_URL,
        "auth": {
            "type": "http_basic",
            "username": account_id,
            "password": personal_access_token,
        },
        "headers": {"Accept": "application/json"},
    }


def flexmail_source(
    account_id: str,
    personal_access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FlexmailResumeConfig],
) -> SourceResponse:
    config = FLEXMAIL_ENDPOINTS[endpoint]

    paginator: BasePaginator
    if config.paginated:
        # `total` is the row count; the paginator stops once offset >= total (or on a short/empty
        # page), matching the hand-rolled `next_offset >= total` termination.
        paginator = OffsetPaginator(limit=PAGE_SIZE, offset_param="offset", limit_param="limit", total_path="total")
    else:
        # Segments, opt-in forms and custom fields return the whole collection in one response.
        paginator = SinglePagePaginator()

    rest_config: RESTAPIConfig = {
        "client": {**_client_config(account_id, personal_access_token), "paginator": paginator},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {"path": config.path, "data_selector": _DATA_SELECTOR},
                "data_map": _strip_links,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.offset:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded so a crash re-fetches the last page (merge dedupes on `id`)
        # rather than skipping it. SinglePagePaginator never yields resume state, so unpaginated
        # endpoints never checkpoint.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(FlexmailResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        column_hints=resource.column_hints,
    )


def validate_credentials(account_id: str, personal_access_token: str) -> tuple[bool, str | None]:
    # Personal access tokens are account-wide, so one probe validates access to every list endpoint.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(personal_access_token,)),
        f"{FLEXMAIL_BASE_URL}{DEFAULT_PROBE_PATH}?limit=1",
        auth=HTTPBasicAuth(account_id, personal_access_token),
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Flexmail account ID or personal access token"
    if status is not None:
        return False, f"Flexmail returned HTTP {status}"
    return False, "Could not validate Flexmail credentials"
