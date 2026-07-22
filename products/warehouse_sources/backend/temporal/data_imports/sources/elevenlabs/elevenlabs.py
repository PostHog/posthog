import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.settings import (
    ELEVENLABS_ENDPOINTS,
    ElevenLabsEndpointConfig,
)

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"


@dataclasses.dataclass
class ElevenLabsResumeConfig:
    # Next-page cursor for whichever endpoint this job syncs. Only one endpoint runs per job, so a
    # single opaque cursor slot is enough; each endpoint sends it under its own cursor param.
    cursor: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "xi-api-key": api_key,
        "Accept": "application/json",
    }


def _to_unix_seconds(value: Any) -> int:
    """Coerce an incremental watermark to Unix seconds for the API's `*_after_unix` filters.

    The incremental field is declared as an integer (Unix seconds), so the pipeline normally hands
    back an int; datetime/date are handled defensively in case a stored value was coerced upstream.
    """
    if isinstance(value, datetime):
        # A naive datetime's timestamp() would assume the server's local timezone, so pin it to UTC
        # to keep incremental boundaries identical across environments.
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return int(value.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())
    return int(value)


def _build_params(
    config: ElevenLabsEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build the constant per-request query params (page size, sort, server-side incremental filter).

    The cursor is added per page by the paginator. The incremental filter is applied on every page (the
    API keeps the time-window filter alongside the cursor), so pagination terminates at `has_more`
    rather than re-walking full history each incremental run.
    """
    params: dict[str, Any] = {"page_size": config.page_size}
    params.update(config.extra_params)

    if (
        should_use_incremental_field
        and config.incremental_param
        and db_incremental_field_last_value is not None
        # `incremental_field` is the user's chosen cursor column; each endpoint exposes exactly one, so
        # only apply the server filter when it matches (or the caller didn't pin one).
        and (incremental_field is None or incremental_field == config.incremental_field)
    ):
        params[config.incremental_param] = _to_unix_seconds(db_incremental_field_last_value)

    return params


class ElevenLabsCursorPaginator(BasePaginator):
    """Cursor pagination where the request param and response cursor key differ per endpoint.

    Termination requires BOTH a truthy ``has_more`` flag AND a next cursor: some endpoints echo a
    stale cursor (the last item id on the final page) alongside ``has_more=False``, so keying off the
    cursor alone would issue one needless extra request.
    """

    def __init__(self, cursor_param: str, cursor_response_key: str) -> None:
        super().__init__()
        self.cursor_param = cursor_param
        self.cursor_response_key = cursor_response_key
        self._cursor_value: Optional[str] = None

    def _apply_cursor(self, request: Request) -> None:
        if self._cursor_value is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor_value

    def init_request(self, request: Request) -> None:
        # Apply a seeded resume cursor to the first request.
        self._apply_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        next_cursor = body.get(self.cursor_response_key) if isinstance(body, dict) else None
        has_more = bool(body.get("has_more")) if isinstance(body, dict) else False
        if has_more and next_cursor:
            self._cursor_value = next_cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._apply_cursor(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor_value} if self._has_next_page and self._cursor_value is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor_value = cursor
            self._has_next_page = True


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe the API key. 200 => valid. 401 => invalid key. 403 => valid key missing a scope.

    At source-create (`schema_name=None`) a 403 is accepted: users may grant only the scopes for the
    endpoints they want, so a missing scope must not block connecting. When probing a specific schema
    a 403 is a genuine per-table scope error and is surfaced. Sync-time 403s are handled separately by
    `get_non_retryable_errors`.

    Any other status (429, 5xx, or an unexpected code) means the key was never actually verified, so
    validation fails rather than saving an unverified key as valid — the user can retry a transient blip.
    """
    config = ELEVENLABS_ENDPOINTS.get(schema_name) if schema_name else None
    probe_path = config.path if config else "/v1/user"
    # Bake the probe's page_size into the URL: validate_via_probe issues a bare GET with no params.
    url = f"{ELEVENLABS_BASE_URL}{probe_path}{'?page_size=1' if config else ''}"

    # Don't follow redirects: requests preserves the custom `xi-api-key` header across a cross-origin
    # 3xx, so a redirect off the fixed API host could replay the key to another origin.
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        url,
        headers=_get_headers(api_key),
    )

    if status is None:
        return False, "Could not reach the ElevenLabs API. Please try again."
    if status == 200:
        return True, None
    if status == 401:
        return False, "Invalid ElevenLabs API key"
    if status == 403:
        if schema_name is None:
            return True, None
        return False, f"Your ElevenLabs API key is missing the permission required to sync `{schema_name}`."
    # A 429/5xx/unexpected status leaves the key unverified. Don't accept it — surface it so the user
    # can retry, rather than saving a source that only fails on its first sync.
    return False, f"Could not verify the ElevenLabs API key (status {status}). Please try again."


def elevenlabs_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ElevenLabsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = ELEVENLABS_ENDPOINTS[endpoint]

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": ELEVENLABS_BASE_URL,
            # Only the non-secret Accept header is set here; the key is injected via `auth` so it's
            # redacted from logs and captured HTTP samples.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "xi-api-key", "location": "header"},
            "paginator": ElevenLabsCursorPaginator(config.cursor_param, config.cursor_response_key),
            # Redact the key and refuse redirects: requests preserves the custom `xi-api-key` header
            # across a cross-origin 3xx, so following one could replay the key to another origin.
            "session": make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Top-level array key; a 200 body missing it is a legit zero-row page (the old
                    # code yielded nothing rather than raising), so the selector is not required.
                    "data_selector": config.items_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(ElevenLabsResumeConfig(cursor=str(state["cursor"])))

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
        sort_mode=config.sort_mode,  # type: ignore[arg-type]
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
    )
