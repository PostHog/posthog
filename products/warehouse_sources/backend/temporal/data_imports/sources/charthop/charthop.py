import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.settings import (
    CHARTHOP_ENDPOINTS,
    ChartHopEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

CHARTHOP_BASE_URL = "https://api.charthop.com"
# No documented max page size; ChartHop's own sync tooling pages with limit=1000. 500 keeps
# the request count low (rate limits are undocumented) while bounding per-page payload size.
PAGE_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 60

AUTH_ERROR_HINT = "ChartHop API authentication or permission error"


class ChartHopAPIError(Exception):
    pass


@dataclasses.dataclass
class ChartHopResumeConfig:
    # ``next`` token of the last fully-yielded page, re-sent as ``from`` on resume.
    from_token: str
    # The incremental start date the interrupted run was using. Reused verbatim on resume:
    # the watermark may have advanced from committed batches, and pairing the saved ``from``
    # id with a narrower date window would ask the API to paginate from an id outside the
    # filtered result set, which has undefined behavior.
    start_date: Optional[str] = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _to_charthop_date(value: Any) -> Optional[str]:
    """Coerce an incremental cursor value to the YYYY-MM-DD format ChartHop's ``date``
    filter expects, clamped to today. A change's effective date can be in the future
    (scheduled promotions/hires); without the clamp the watermark would start future runs
    past changes entered later for earlier dates."""
    if isinstance(value, datetime):
        value = (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).date()
    elif isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return None
    if not isinstance(value, date):
        return None
    today = datetime.now(UTC).date()
    return min(value, today).isoformat()


def _endpoint_path(config: ChartHopEndpointConfig, org_id: str) -> str:
    # Encode the org id as a single path segment so a crafted value (slashes, query
    # delimiters) can't redirect the request to a different endpoint with the stored token.
    return config.path.format(org_id=quote(org_id, safe=""))


def resolve_org_id(api_key: str, configured_org_id: Optional[str]) -> str:
    """Resolve the org id (or slug) every data endpoint needs in its path.

    Self-serve ChartHop API tokens are generated per org, so ``GET /v1/org`` normally
    returns exactly one org and the field can stay empty. A token that can see several
    orgs must say which one to sync.
    """
    if configured_org_id and configured_org_id.strip():
        return configured_org_id.strip()

    response = make_tracked_session(redact_values=(api_key,)).get(
        f"{CHARTHOP_BASE_URL}/v1/org?limit=2", headers=_get_headers(api_key), timeout=REQUEST_TIMEOUT_SECONDS
    )
    if response.status_code in (401, 403):
        raise ChartHopAPIError(f"{response.status_code} Client Error: {AUTH_ERROR_HINT} for url /v1/org")
    response.raise_for_status()

    orgs = response.json().get("data", [])
    if len(orgs) == 0:
        raise ChartHopAPIError("ChartHop API token has no access to any organization")
    if len(orgs) > 1:
        raise ChartHopAPIError(
            "ChartHop API token can access multiple organizations. Set the organization ID or slug on the source."
        )
    return orgs[0]["id"]


def check_access(api_key: str, org_id: Optional[str], schema_name: Optional[str]) -> tuple[int, Optional[str]]:
    """Probe the API to validate credentials.

    Returns a normalized ``(status, message)``: 200 = reachable, 401 = bad token,
    403 = valid token without access, 404 = org not found, 0 = network/unexpected error.
    Validating a specific schema probes that endpoint with ``limit=1`` so tokens scoped
    to a subset of the data fail fast on the schemas they can't read.
    """
    try:
        resolved_org_id = resolve_org_id(api_key, org_id)
    except ChartHopAPIError as e:
        message = str(e)
        if "401" in message:
            return 401, message
        if "403" in message:
            return 403, message
        return 0, message
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        return status, str(e)
    except Exception as e:
        return 0, f"Could not connect to ChartHop: {e}"

    if schema_name is None:
        return 200, None

    config = CHARTHOP_ENDPOINTS[schema_name]
    path = _endpoint_path(config, resolved_org_id)
    query = urlencode({"limit": 1, **config.extra_params})
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{CHARTHOP_BASE_URL}{path}?{query}",
        headers=_get_headers(api_key),
        timeout=15,
    )
    if status is None:
        return 0, "Could not connect to ChartHop"
    return status, None


def charthop_source(
    api_key: str,
    org_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ChartHopResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CHARTHOP_ENDPOINTS[endpoint]
    path = _endpoint_path(config, org_id)

    initial_paginator_state: Optional[dict[str, Any]] = None
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        initial_paginator_state = {"cursor": resume.from_token}
        # The saved window wins over the advanced watermark — see ChartHopResumeConfig.
        start_date = resume.start_date
    else:
        start_date = (
            _to_charthop_date(db_incremental_field_last_value)
            if should_use_incremental_field and db_incremental_field_last_value is not None
            else None
        )

    params: dict[str, Any] = {"limit": PAGE_SIZE, **config.extra_params}
    # The ``next`` token is a bare entity id, not a full query, so filters are re-sent on
    # every page — the date window stays applied across the whole pagination walk.
    if config.incremental_param is not None and start_date is not None:
        params[config.incremental_param] = start_date

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CHARTHOP_BASE_URL,
            "headers": {"Accept": "application/json"},
            # Auth (Bearer) via the framework auth config so its value is redacted from logs.
            "auth": {"type": "bearer", "token": api_key},
            # Every ChartHop list endpoint pages cursor-by-id: ``next`` in the body is
            # re-sent as the ``from`` query param; a missing/empty ``next`` ends the walk.
            "paginator": JSONResponseCursorPaginator(cursor_path="next", cursor_param="from"),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": path,
                    "params": params,
                    "data_selector": "data",
                },
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the framework calls this AFTER a page is
        # yielded, so a crash re-yields the last page (merge dedupes on the primary key)
        # rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(
                ChartHopResumeConfig(from_token=str(state["cursor"]), start_date=start_date)
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # The date window is injected into ``params`` above (resume must reuse the saved
        # window verbatim), so the framework's incremental plumbing is not used.
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_key,
        # The change endpoint documents ascending effective-date order as its default
        # (``desc=false``); every other endpoint is full refresh, where sort mode doesn't
        # gate watermark checkpointing.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
