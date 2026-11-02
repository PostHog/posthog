import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.settings import (
    PAGE_SIZE,
    QUALAROO_ENDPOINTS,
)

QUALAROO_BASE_URL = "https://api.qualaroo.com/api/v1"
# Cheap endpoint used to confirm the credentials are genuine. The API key/secret pair is
# account-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/nudges.json"


@dataclasses.dataclass(frozen=False)
class QualarooResumeConfig:
    # Offset of the next page to fetch. Offset pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    offset: int = 0
    # Progress of an endpoint that is listed once per nudge: the nudges that are done, the nudge in
    # progress, and the page cursor of that nudge. The shared fan-out helper owns the shape.
    fanout_state: Optional[dict[str, Any]] = None
    # `end_date` fixed at sync start, so responses that arrive mid fan-out are left for the next run.
    sync_end: Optional[str] = None


def _client_config(api_key: str, api_secret: str) -> ClientConfig:
    return {
        "base_url": QUALAROO_BASE_URL,
        "headers": {"Accept": "application/json"},
        # Qualaroo uses HTTP Basic auth with the API key as username and the secret as password.
        "auth": {"type": "http_basic", "username": api_key, "password": api_secret},
        # Qualaroo has no top-level `total`; termination is a short/empty page (OffsetPaginator default).
        "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None),
    }


def _to_unix_seconds(value: Any) -> Optional[int]:
    parsed = parse_datetime_value(value)
    if parsed is None:
        # No watermark yet: omit `start_date`, so the API starts from the first response.
        return None
    # The docs do not say whether `start_date` is inclusive. A one-second overlap keeps rows that
    # share the watermark second, and merge dedupes the rows it reads again.
    return int((parsed - timedelta(seconds=1)).timestamp())


def _incremental_window(cursor_path: str, sync_end: str) -> IncrementalConfig:
    return {
        "cursor_path": cursor_path,
        "start_param": "start_date",
        "end_param": "end_date",
        "end_value": sync_end,
        "convert": _to_unix_seconds,
    }


def _fanout_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[QualarooResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: Optional[str],
) -> SourceResponse:
    config = QUALAROO_ENDPOINTS[endpoint]
    assert config.fanout is not None

    initial_fanout_state: Optional[dict[str, Any]] = None
    sync_end: Optional[str] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_fanout_state = resume.fanout_state
            sync_end = resume.sync_end
    run_sync_end = sync_end or datetime.now(UTC).isoformat()

    def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(QualarooResumeConfig(fanout_state=state, sync_end=run_sync_end))

    resource = build_dependent_resource(
        endpoint_configs=QUALAROO_ENDPOINTS,
        child_endpoint=endpoint,
        fanout=config.fanout,
        # Survey answers are free text that the sample scrubbers cannot reliably redact.
        client_config={**_client_config(api_key, api_secret), "capture": False},
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=db_incremental_field_last_value,
        should_use_incremental_field=should_use_incremental_field,
        incremental_field=incremental_field,
        incremental_config_factory=lambda cursor_path: _incremental_window(cursor_path, run_sync_end),
        # The client OffsetPaginator already sends `limit` on every request.
        page_size_param=None,
        parent_endpoint_extra={"data_selector_malformed_retryable": True},
        child_endpoint_extra={"data_selector_malformed_retryable": True},
        resume_hook=save_fanout_checkpoint,
        initial_paginator_state=initial_fanout_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def qualaroo_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[QualarooResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = QUALAROO_ENDPOINTS[endpoint]
    if config.fanout is not None:
        return _fanout_source(
            api_key,
            api_secret,
            endpoint,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
        )

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, api_secret),
        # Per-resource settings are fully specified below, so no shared defaults are needed.
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # Qualaroo list endpoints return a bare JSON array; a 200 whose body isn't a list
                    # is treated as a transient shape glitch and retried (not failed loud).
                    "data_selector_malformed_retryable": True,
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
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on `id`) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(QualarooResumeConfig(offset=int(state["offset"])))

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
        partition_count=1,
        partition_size=1,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, api_secret: str) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the account-wide key/secret pair.

    Maps the probe result to the same messages the hand-rolled implementation returned: 200 valid,
    401/403 bad credentials, any other status surfaced verbatim, and an unreachable probe reported
    as an unvalidated (rather than failed) source.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key, api_secret)),
        f"{QUALAROO_BASE_URL}{DEFAULT_PROBE_PATH}?limit=1&offset=0",
        auth=HTTPBasicAuth(api_key, api_secret),
        headers={"Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Qualaroo API key or secret"
    if status is None:
        return False, "Could not validate Qualaroo credentials"
    return False, f"Qualaroo returned HTTP {status}"
