import re
import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.settings import (
    FIREWORKS_AI_ENDPOINTS,
    PAGE_SIZE,
)

FIREWORKS_AI_BASE_URL = "https://api.fireworks.ai/v1"

_ACCOUNT_ID_REGEX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclasses.dataclass
class FireworksAIResumeConfig:
    # Opaque nextPageToken from the last committed page. The API requires all other params to
    # match the original call, so the transport re-sends the same pageSize alongside it.
    page_token: str


def normalize_account_id(account_id: str) -> str:
    """Reduce whatever the user entered to the bare Fireworks account id.

    Users may paste the full resource prefix ("accounts/my-account") shown throughout the
    Fireworks docs and firectl output. Without normalizing, the request path becomes
    /v1/accounts/accounts/my-account/... which can never resolve.
    """
    account_id = account_id.strip().strip("/")
    if account_id.startswith("accounts/"):
        account_id = account_id[len("accounts/") :]
    return account_id


def is_valid_account_id(account_id: str) -> bool:
    return _ACCOUNT_ID_REGEX.match(account_id) is not None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def fireworks_ai_source(
    api_key: str,
    account_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FireworksAIResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = FIREWORKS_AI_ENDPOINTS[endpoint]
    path = f"accounts/{normalize_account_id(account_id)}/{endpoint_config.path}"

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": FIREWORKS_AI_BASE_URL,
            # Auth (Bearer) is supplied via the framework auth config so the key is redacted from
            # logs and raised error messages; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            # AIP list pagination: nextPageToken in the body echoed back as the pageToken query
            # param; an absent/empty token ends the walk.
            "paginator": JSONResponseCursorPaginator(cursor_path="nextPageToken", cursor_param="pageToken"),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": path,
                    # pageSize is re-sent on every page; the API requires it to match the original
                    # call alongside the pageToken.
                    "params": {"pageSize": PAGE_SIZE},
                    # Proto3 JSON omits empty repeated fields, so a missing collection key is a
                    # legitimate empty page (not a shape error) — no data_selector_required.
                    "data_selector": endpoint_config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.page_token:
            initial_paginator_state = {"cursor": resume.page_token}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(FireworksAIResumeConfig(page_token=str(state["cursor"])))

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
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[endpoint_config.partition_key],
        column_hints=resource.column_hints,
    )


def get_status_code(api_key: str, account_id: str, endpoint: str | None = None) -> int:
    """Cheap probe used by credential validation. Returns the HTTP status code."""
    if endpoint is not None and endpoint in FIREWORKS_AI_ENDPOINTS:
        path = FIREWORKS_AI_ENDPOINTS[endpoint].path
    else:
        # Models is account-scoped and readable by any key — a cheap token + account check.
        path = FIREWORKS_AI_ENDPOINTS["models"].path

    url = f"{FIREWORKS_AI_BASE_URL}/accounts/{normalize_account_id(account_id)}/{path}"
    response = make_tracked_session(redact_values=(api_key,)).get(
        url, params={"pageSize": 1}, headers=_get_headers(api_key), timeout=10
    )
    return response.status_code
