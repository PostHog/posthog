import dataclasses
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.tempo.settings import (
    TEMPO_ENDPOINTS,
    TempoEndpointConfig,
)

# Universal base path; Tempo also offers api.eu.tempo.io / api.us.tempo.io for geographic routing,
# but the universal host serves every region.
TEMPO_BASE_URL = "https://api.tempo.io/4"
# List endpoints default to 50 rows per page; 100 keeps round trips down without risking
# undocumented per-endpoint caps.
PAGE_SIZE = 100
# The plans endpoint requires a `from`/`to` window, so a full sync sends a wide fixed one. Plans
# are resource allocations that can extend into the future, hence the years of headroom.
PLANS_WINDOW_START = "2001-01-01"
PLANS_WINDOW_YEARS_AHEAD = 5
# Cheap endpoint used to confirm an API token is genuine at source-create. Tempo tokens carry
# granular scopes, so a 403 here still proves the token itself is valid.
DEFAULT_PROBE_ENDPOINT = "worklogs"


@dataclasses.dataclass
class TempoResumeConfig:
    # Full URL of the next page, taken verbatim from the API's `metadata.next` (it embeds limit,
    # offset, and any filters). A crashed sync resumes from the page after the last one yielded;
    # merge dedupes the re-pulled page on the primary key. `None` means start from the first page.
    next_url: str | None = None


def _headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}


def _plans_window() -> tuple[str, str]:
    end = date.today() + timedelta(days=365 * PLANS_WINDOW_YEARS_AHEAD)
    return PLANS_WINDOW_START, end.isoformat()


def _format_updated_from(value: Any) -> str:
    # `updatedFrom` accepts "yyyy-MM-dd" or "yyyy-MM-dd'T'HH:mm:ss'Z'" (inclusive); the boundary
    # row is re-fetched and merge dedupes it on the primary key. The watermark round-trips from
    # Tempo's own `updatedAt` (always UTC), so a naive datetime is treated as UTC, not local time.
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _probe_params(config: TempoEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.paginated:
        params["limit"] = 1
    if config.requires_date_window:
        today = date.today().isoformat()
        params["from"] = today
        params["to"] = today
    return params


def _build_initial_params(
    config: TempoEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.paginated:
        params["limit"] = PAGE_SIZE
    if config.requires_date_window:
        window_from, window_to = _plans_window()
        params["from"] = window_from
        params["to"] = window_to
    if config.order_by:
        params["orderBy"] = config.order_by

    if should_use_incremental_field:
        advertised = {f["field"] for f in config.incremental_fields}
        if not config.incremental_param or incremental_field not in advertised:
            raise ValueError(f"Tempo endpoint '{config.name}' does not support incremental field '{incremental_field}'")
        if db_incremental_field_last_value:
            params[config.incremental_param] = _format_updated_from(db_incremental_field_last_value)

    return params


def tempo_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TempoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = TEMPO_ENDPOINTS[endpoint]

    # The watermark/date-window/order/limit filters are baked into the first request's params;
    # `metadata.next` carries them forward on every subsequent page, so the paginator never
    # re-sends them.
    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TEMPO_BASE_URL,
            # Auth (Bearer) rides in the framework auth config so its value is redacted from logs
            # and raised error messages; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_token},
            # `metadata.next` is a full next-page URL (absent on the last page and on unpaginated
            # endpoints, which terminates pagination).
            "paginator": JSONResponsePaginator(next_url_path="metadata.next"),
            # `metadata.next` is server-controlled and the session carries the Bearer token, so a
            # tampered response or poisoned resume URL could point the credentialed request off-host.
            # Pin every request (next-page + seeded resume URLs) to the Tempo API host and reject
            # redirects so the token can't be exfiltrated. allowed_hosts=[] means "base_url host only".
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        # Per-resource settings are fully specified below, so no shared defaults are needed.
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "results",
                    # A 200 whose body isn't the expected `{"results": [...], ...}` envelope (non-dict,
                    # or missing/non-list `results`) is treated as a transient bad shape and retried —
                    # matching the old TempoRetryableError raised on an unexpected payload.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; the checkpoint lands AFTER a page is yielded so a
        # crash re-yields the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(TempoResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # The watermark is already applied via params above, so the framework's incremental
        # injection is intentionally left unused.
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
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
    )


def check_access(api_token: str, endpoint: str = DEFAULT_PROBE_ENDPOINT) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to check the API token.

    Returns ``(status, message)``: ``200`` reachable, ``401`` invalid token, ``403`` valid token
    missing the endpoint's view scope, ``0`` for a connection problem, other HTTP status otherwise.
    """
    config = TEMPO_ENDPOINTS[endpoint]
    probe_params = _probe_params(config)
    url = f"{TEMPO_BASE_URL}{config.path}"
    if probe_params:
        url = f"{url}?{urlencode(probe_params)}"

    # allow_redirects=False so a 3xx can't silently move the credentialed request off the
    # validated host (SSRF).
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,), allow_redirects=False),
        url,
        headers=_headers(api_token),
        timeout=15,
    )
    if status is None:
        return 0, "Could not connect to Tempo"
    if status in (401, 403):
        return status, None
    if status != 200:
        return status, f"Tempo returned HTTP {status}"
    return 200, None


def validate_credentials(api_token: str, endpoint: str | None = None) -> tuple[bool, str | None]:
    status, message = check_access(api_token, endpoint or DEFAULT_PROBE_ENDPOINT)
    if status == 200:
        return True, None
    if status == 401:
        return False, "Invalid Tempo API token"
    if status == 403:
        # Tempo tokens carry granular scopes. At source-create (no endpoint) a 403 still proves the
        # token is genuine — the user may only have granted scopes for the tables they'll sync.
        if endpoint is None:
            return True, None
        return False, f"Your Tempo API token is missing the view scope for '{endpoint}'"
    return False, message or "Could not validate Tempo API token"
