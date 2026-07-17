import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
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
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.settings import (
    ELASTICEMAIL_ENDPOINTS,
    PAGE_SIZE,
    ElasticEmailEndpointConfig,
)

ELASTICEMAIL_BASE_URL = "https://api.elasticemail.com/v4"

# Marker carried by the auth-failure error so `get_non_retryable_errors` can match credential failures.
# Elastic Email returns these as HTTP 400 with an `{"Error": "APIKey Expired"}` style body rather than
# the more usual 401/403, so we can't match on the status line alone.
AUTH_ERROR_MARKER = "Elastic Email API authentication failed"

# User-facing message raised on an auth failure during a sync. Carries AUTH_ERROR_MARKER so the
# pipeline's non-retryable classifier stops hammering a dead key instead of retrying it.
AUTH_ERROR_MESSAGE = f"{AUTH_ERROR_MARKER}: the API key is invalid, expired, or missing read permissions."

# A cheap, parameter-free endpoint used to confirm a key is genuine at source-create time.
VALIDATION_PATH = "/statistics"

# Substrings that mark a 400 body as a credential problem (Elastic Email signals a bad/expired/
# under-scoped key with HTTP 400, not 401/403). `_is_auth_error_body` matches these case-insensitively;
# `_auth_response_actions` matches the common casings the API actually returns, since the framework's
# response-action content match is case-sensitive.
_AUTH_BODY_TOKENS = ("apikey", "api key", "access token", "unauthorized", "expired")


@dataclasses.dataclass
class ElasticEmailResumeConfig:
    # Next offset to request. Elastic Email paginates with limit/offset, so the offset alone is enough
    # to resume mid-endpoint; the incremental `from` window is re-derived from the stored cursor each run.
    offset: int = 0


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-ElasticEmail-ApiKey": api_key,
        "Accept": "application/json",
    }


def _format_datetime(value: Any) -> str:
    """Format a datetime/date as the `YYYY-MM-DDThh:mm:ss` (UTC, no offset) shape Elastic Email expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime/date cursor at now so the `from` filter never asks for impossible records."""
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _build_url(path: str, params: dict[str, Any]) -> str:
    # doseq=True expands list values (e.g. scopeType=Personal&scopeType=Global) into repeated params.
    return f"{ELASTICEMAIL_BASE_URL}{path}?{urlencode(params, doseq=True)}"


def _is_auth_error_body(status_code: int, body: str) -> bool:
    if status_code in (401, 403):
        return True
    if status_code != 400:
        return False
    lowered = body.lower()
    return any(token in lowered for token in _AUTH_BODY_TOKENS)


def _static_params(
    config: ElasticEmailEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    """Non-pagination query params for an endpoint (limit/offset are added by the paginator).

    Mirrors the old `_build_params`: static per-endpoint params plus, for an incremental endpoint with
    a cursor, the server-side `from` time filter (future cursors clamped to now).
    """
    params: dict[str, Any] = dict(config.extra_params)

    # Only endpoints that advertise an incremental field have a server-side `from` time filter.
    if should_use_incremental_field and config.incremental_fields and db_incremental_field_last_value:
        params["from"] = _format_datetime(_clamp_future_value_to_now(db_incremental_field_last_value))

    return params


def _auth_response_actions() -> list[ResponseAction]:
    """Response actions that raise a permanent, non-retryable auth error carrying AUTH_ERROR_MARKER.

    401/403 are auth failures regardless of body; a 400 is an auth failure only when its body names a
    credential problem. Non-auth 4xx match nothing here and fall through to `raise_for_status` (an
    HTTPError the pipeline retries), exactly as the old `_fetch_page` did.
    """
    actions: list[ResponseAction] = [
        {"status_code": 401, "action": "raise", "message": AUTH_ERROR_MESSAGE},
        {"status_code": 403, "action": "raise", "message": AUTH_ERROR_MESSAGE},
    ]
    # The content match is case-sensitive, so expand each token to the casings Elastic Email returns.
    seen: set[str] = set()
    for token in _AUTH_BODY_TOKENS:
        for variant in (token, token.upper(), token.title(), "API key", "APIKey"):
            if variant in seen:
                continue
            seen.add(variant)
            actions.append({"status_code": 400, "content": variant, "action": "raise", "message": AUTH_ERROR_MESSAGE})
    return actions


def validate_credentials(
    api_key: str, path: str = VALIDATION_PATH, extra_params: Optional[dict[str, list[str] | str]] = None
) -> bool:
    """Probe a single endpoint to confirm the key is accepted. `path` lets callers check a specific scope."""
    params: dict[str, Any] = {"limit": 1, "offset": 0, **(extra_params or {})}
    url = _build_url(path, params)
    try:
        # redact_values masks the API key in logged URLs and captured HTTP samples; the X-ElasticEmail-ApiKey
        # header name isn't in the transport's generic auth denylist, so we redact the value explicitly.
        response = make_tracked_session(redact_values=(api_key,)).get(url, headers=_get_headers(api_key), timeout=10)
    except requests.RequestException:
        # A transport failure (DNS, connection, timeout) isn't a credential verdict, but at source-create
        # time we can only report valid/invalid — treat an unreachable API as "can't validate" → invalid.
        return False
    if response.ok:
        return True
    return not _is_auth_error_body(response.status_code, response.text or "")


def elasticemail_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ElasticEmailResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ELASTICEMAIL_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": ELASTICEMAIL_BASE_URL,
            # Elastic Email carries the key in the X-ElasticEmail-ApiKey header; framework auth redacts it.
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-ElasticEmail-ApiKey", "location": "header"},
            "headers": {"Accept": "application/json"},
            # limit/offset pagination over a bare JSON array; a short page (data < limit) ends it, just
            # like the old `len(items) < PAGE_SIZE` check. No total is reported in body or header.
            "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": _static_params(config, should_use_incremental_field, db_incremental_field_last_value),
                    # Every v4 list endpoint returns a bare JSON array; require a list so an unexpected
                    # object payload fails loud instead of being synced as a single row.
                    "data_selector_required": True,
                    # Surface a bad/expired/under-scoped key (HTTP 400/401/403) as a permanent auth error.
                    "response_actions": _auth_response_actions(),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # OffsetPaginator only reports state while more pages remain, so the final short page saves
        # nothing — a crash re-fetches from the last persisted offset rather than skipping rows.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(ElasticEmailResumeConfig(offset=int(state["offset"])))

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
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Events are fetched oldest-first (orderBy=DateAscending); the other endpoints are full refresh
        # where order does not affect correctness.
        sort_mode="asc",
    )
