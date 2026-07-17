import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.settings import KOYEB_ENDPOINTS

KOYEB_BASE_URL = "https://app.koyeb.com"

# Koyeb caps list page sizes at 100 (default 10); request the max to minimize round-trips.
PAGE_SIZE = 100

# Backstop against an endpoint that ignores `offset` (which would otherwise re-serve page one
# forever). Resumable state means an interrupted sync picks back up, so this is a runaway guard,
# not a coverage limit — at 100 rows/page it allows ~1M rows before stopping.
MAX_PAGES = 10_000

# /v1/usages/details requires a time window; Koyeb launched in 2019, so this floor covers any
# organization's full usage history.
USAGE_WINDOW_START = "2019-01-01T00:00:00Z"

# Placeholder written over plaintext secrets pulled out of deployment definitions, so the column
# still shows a value existed without exposing it.
REDACTED_SECRET = "[redacted by PostHog]"


@dataclasses.dataclass
class KoyebResumeConfig:
    # The `offset` of the next page to fetch. Rows are requested in ascending order (where the
    # endpoint supports `order`), so rows appended mid-sync land after the offset and can't shift
    # earlier pages underneath it.
    offset: int = 0


def _scrub_definition_secrets(row: dict[str, Any]) -> dict[str, Any]:
    """Redact plaintext secrets embedded in a deployment `definition` in place.

    `definition.env[].value` is a plaintext environment value and `definition.config_files[].content`
    is raw config-file content — both can hold credentials. We keep the surrounding structure (env
    keys, secret *references*, file paths) so the row stays useful, but overwrite the secret-bearing
    values. Anything that isn't shaped as expected is left untouched.
    """
    definition = row.get("definition")
    if not isinstance(definition, dict):
        return row

    env = definition.get("env")
    if isinstance(env, list):
        for var in env:
            # `secret` is only a reference to a Koyeb secret name (safe); `value` is the plaintext.
            if isinstance(var, dict) and var.get("value") is not None:
                var["value"] = REDACTED_SECRET

    config_files = definition.get("config_files")
    if isinstance(config_files, list):
        for config_file in config_files:
            if isinstance(config_file, dict) and config_file.get("content") is not None:
                config_file["content"] = REDACTED_SECRET

    return row


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _format_time_value(value: Any) -> str:
    """Format an incremental cursor as the RFC 3339 UTC timestamp Koyeb's date-time params expect."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    return str(value)


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Confirm the API token is genuine via GET /v1/account/profile — the cheapest authenticated
    probe. Koyeb tokens are organization-scoped with no per-resource permissions, so one probe
    covers every endpoint."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{KOYEB_BASE_URL}/v1/account/profile",
        headers=_get_headers(api_token),
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid or unauthorized Koyeb API token"
    if status is None:
        return False, "Could not reach the Koyeb API"
    return False, f"Koyeb API error: {status}"


def koyeb_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[KoyebResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = KOYEB_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    if config.supports_order:
        # Always request ascending so offset pagination stays stable while new rows are appended.
        params["order"] = "asc"
    if config.requires_time_window:
        # /v1/usages/details rejects requests without a window; fix `ending_time` once per run so the
        # row set behind the offsets doesn't drift while paginating.
        params["starting_time"] = USAGE_WINDOW_START
        params["ending_time"] = _format_time_value(datetime.now(UTC))

    endpoint_config: dict[str, Any] = {
        "path": config.path,
        "params": params,
        # A missing data key yields an empty page and stops the paginator, matching the old
        # `data.get(key) or []` (no raise on a shape change).
        "data_selector": config.response_data_key,
    }

    # Only `instances` documents a server-side `starting_time` filter, and only inject it in
    # incremental mode — full refresh omits it entirely, as before. Merge dedupes the overlap on `id`.
    if (
        should_use_incremental_field
        and config.starting_time_param
        and not config.requires_time_window
        and db_incremental_field_last_value is not None
    ):
        endpoint_config["incremental"] = {
            "start_param": config.starting_time_param,
            "convert": _format_time_value,
        }

    client: dict[str, Any] = {
        "base_url": KOYEB_BASE_URL,
        # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs
        # and raised errors; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_token},
        # Koyeb has no top-level `total`; termination is short/empty page. `maximum_offset` backstops
        # an endpoint that ignores `offset` from re-serving page one forever.
        "paginator": OffsetPaginator(
            limit=PAGE_SIZE,
            total_path=None,
            maximum_offset=MAX_PAGES * PAGE_SIZE,
        ),
    }
    if config.scrub_definition_secrets:
        # HTTP sample capture stores the raw response body BEFORE the definition scrub runs, and the
        # capture path's name-based scrubbers can't recognise plaintext env values or config-file
        # content — so secret-scrubbed endpoints opt their session out of capture entirely.
        client["session"] = make_tracked_session(capture=False, redact_values=(api_token,))

    resource_config: dict[str, Any] = {"name": endpoint, "endpoint": endpoint_config}
    if config.scrub_definition_secrets:
        # Redact plaintext secrets embedded in deployment definitions before they are persisted.
        resource_config["data_map"] = _scrub_definition_secrets

    rest_config: RESTAPIConfig = {
        "client": client,
        "resources": [resource_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the in-flight page (merge dedupes) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(KoyebResumeConfig(offset=int(state["offset"])))

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
        # Endpoints with an `order` param are requested ascending; the rest are full refresh only,
        # where the watermark is never consulted.
        sort_mode="asc",
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
