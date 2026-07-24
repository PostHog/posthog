import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.settings import (
    AVIATIONSTACK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

AVIATIONSTACK_BASE_URL = "https://api.aviationstack.com/v1"
DEFAULT_PAGE_SIZE = 100

# aviationstack returns HTTP 200 with an error envelope (`{"error": {"code": ...}}`). The single
# transient body code is retried in-process; every listed permanent code (bad/blocked key, plan
# gating, exhausted monthly quota) fails fast and is surfaced with a stable `[code]` token matched by
# AviationstackSource.get_non_retryable_errors. An unrecognized error code has no `data` key, so the
# framework fails loud on the missing selector (data_selector_required) rather than syncing 0 rows.
_RETRYABLE_BODY_CODE = "rate_limit_reached"
_PERMANENT_BODY_CODES = (
    "invalid_access_key",
    "missing_access_key",
    "inactive_user",
    "function_access_restricted",
    "https_access_restricted",
    "usage_limit_reached",
)


@dataclasses.dataclass
class AviationstackResumeConfig:
    # Offset of the next page to fetch — aviationstack uses limit/offset pagination.
    next_offset: int


def _response_actions() -> list[ResponseAction]:
    # The `content` matches the quoted error code as it appears in the JSON body, independent of
    # whitespace around the colon. Retryable code first; each permanent code raises a secret-free,
    # non-retryable error whose message carries the `[code]` token get_non_retryable_errors matches.
    actions: list[ResponseAction] = [
        {
            "content": f'"{_RETRYABLE_BODY_CODE}"',
            "action": "retry",
            "message": f"aviationstack API error (retryable) [{_RETRYABLE_BODY_CODE}]",
        }
    ]
    actions.extend(
        {
            "content": f'"{code}"',
            "action": "raise",
            "message": f"aviationstack API error [{code}]",
        }
        for code in _PERMANENT_BODY_CODES
    )
    # aviationstack also returns hard 401/403 for a bad key / plan gating. Author a secret-free
    # message (the access_key rides in the query string, so a bare raise_for_status would leak it)
    # that still matches the stable host prefix in get_non_retryable_errors.
    actions.append(
        {
            "status_code": 401,
            "action": "raise",
            "message": "401 Client Error: Unauthorized for url: https://api.aviationstack.com",
        }
    )
    actions.append(
        {
            "status_code": 403,
            "action": "raise",
            "message": "403 Client Error: Forbidden for url: https://api.aviationstack.com",
        }
    )
    return actions


def aviationstack_source(
    access_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AviationstackResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = AVIATIONSTACK_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": AVIATIONSTACK_BASE_URL,
            # access_key rides in the query string; the framework auth redacts its value from every
            # logged URL, captured sample, and raised error message.
            "auth": {"type": "api_key", "api_key": access_key, "name": "access_key", "location": "query"},
            "paginator": OffsetPaginator(limit=DEFAULT_PAGE_SIZE, total_path="pagination.total"),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "data_selector": "data",
                    # A 200 body without `data` means an error envelope (recognized codes are caught
                    # by response_actions first) or a changed shape — fail loud, don't sync 0 rows.
                    "data_selector_required": True,
                    "response_actions": _response_actions(),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.next_offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge/replace dedupes) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(AviationstackResumeConfig(next_offset=int(state["offset"])))

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
    )


def validate_credentials(access_key: str) -> bool:
    # `/countries` is a static reference endpoint available on every plan (including free), so it's a
    # cheap probe that the access key is genuine without depending on a paid-tier endpoint. A bad key
    # can surface either as a non-200 status or as an HTTP 200 with a body-level error envelope, so
    # both are checked here (validate_via_probe only inspects the status).
    url = f"{AVIATIONSTACK_BASE_URL}/countries"
    params: dict[str, Any] = {"access_key": access_key, "limit": 1}
    try:
        session = make_tracked_session(redact_values=(access_key,))
        response = session.get(url, params=params, timeout=10)
    except Exception:
        return False

    if response.status_code != 200:
        return False

    try:
        body = response.json()
    except ValueError:
        return False

    return not (isinstance(body, dict) and bool(body.get("error")))
