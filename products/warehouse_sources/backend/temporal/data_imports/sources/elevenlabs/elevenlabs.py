import dataclasses
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    FanoutEndpointLike,
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.settings import (
    ELEVENLABS_ENDPOINTS,
    ElevenLabsEndpointConfig,
)

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"
REDACTED = "[REDACTED]"


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


def _redact_header_values(headers: Any) -> Any:
    if not isinstance(headers, dict):
        return headers
    # Non-string values are secret, env var, or dynamic variable references, not the secret itself.
    return {name: REDACTED if isinstance(value, str) else value for name, value in headers.items()}


def _redact_tool_secrets(row: dict[str, Any]) -> dict[str, Any]:
    tool_config = row.get("tool_config")
    api_schema = tool_config.get("api_schema") if isinstance(tool_config, dict) else None
    if isinstance(api_schema, dict) and "request_headers" in api_schema:
        api_schema["request_headers"] = _redact_header_values(api_schema["request_headers"])
    details = row.get("tool_call_details")
    if isinstance(details, dict) and "headers" in details:
        details["headers"] = _redact_header_values(details["headers"])
    return row


def _redact_phone_number_secrets(row: dict[str, Any]) -> dict[str, Any]:
    # `provider_config` is the deprecated alias of `outbound_trunk`, so both carry the same SIP headers.
    for key in ("outbound_trunk", "provider_config"):
        trunk = row.get(key)
        if isinstance(trunk, dict) and "headers" in trunk:
            trunk["headers"] = _redact_header_values(trunk["headers"])
    return row


# Webhook tools can carry literal credentials in their configured request headers, executions echo the
# headers that were sent, and SIP trunks can send custom auth headers on each call. Warehouse readers
# must not be able to read them back.
SECRET_REDACTORS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "tools": _redact_tool_secrets,
    "tool_executions": _redact_tool_secrets,
    "phone_numbers": _redact_phone_number_secrets,
}


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
    params: dict[str, Any] = {} if config.page_size is None else {config.page_size_param: config.page_size}
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


def _paginator(config: ElevenLabsEndpointConfig) -> BasePaginator:
    if config.page_number_param is not None:
        return PageNumberPaginator(base_page=1, page_param=config.page_number_param)
    if config.cursor_param is None or config.cursor_response_key is None:
        return SinglePagePaginator()
    return ElevenLabsCursorPaginator(config.cursor_param, config.cursor_response_key)


def _client_config(api_key: str, paginator: BasePaginator) -> ClientConfig:
    return {
        "base_url": ELEVENLABS_BASE_URL,
        # Only the non-secret Accept header is set here; the key is injected via `auth` so it's
        # redacted from logs and captured HTTP samples.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_key, "name": "xi-api-key", "location": "header"},
        "paginator": paginator,
        # Redact the key and refuse redirects: requests preserves the custom `xi-api-key` header
        # across a cross-origin 3xx, so following one could replay the key to another origin.
        "session": make_tracked_session(redact_values=(api_key,), allow_redirects=False),
    }


_INVALID_API_KEY_MESSAGE = (
    "Your ElevenLabs API key is invalid or has been revoked. Create a new key in your "
    "ElevenLabs account settings, then try again."
)


def _is_missing_permission(response: Response) -> bool:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return False
    return isinstance(detail, dict) and detail.get("status") == "missing_permissions"


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe the API key. 200 => valid. 401 => invalid key. 403 => valid key missing a scope.

    ElevenLabs also answers a valid key that lacks a scope with a 401 whose body carries
    `detail.status == "missing_permissions"`, so that 401 is a missing scope too, not an invalid key.

    At source-create (`schema_name=None`) a missing scope is accepted: users may grant only the scopes
    for the endpoints they want, so a missing scope must not block connecting. When probing a specific
    schema it is a genuine per-table scope error and is surfaced. Sync-time 403s are handled separately
    by `get_non_retryable_errors`.

    Any other status (429, 5xx, or an unexpected code) means the key was never actually verified, so
    validation fails rather than saving an unverified key as valid — the user can retry a transient blip.
    """
    config = ELEVENLABS_ENDPOINTS.get(schema_name) if schema_name else None
    # A fan-out child's path needs a parent id, and the parent listing needs the same permission.
    if config is not None and config.fanout is not None:
        config = ELEVENLABS_ENDPOINTS[config.fanout.parent_name]
    probe_path = config.path if config else "/v1/user"
    # Bake the probe's page_size into the URL: the probe issues a bare GET with no params.
    url = f"{ELEVENLABS_BASE_URL}{probe_path}{f'?{config.page_size_param}=1' if config and config.page_size else ''}"

    # Don't follow redirects: requests preserves the custom `xi-api-key` header across a cross-origin
    # 3xx, so a redirect off the fixed API host could replay the key to another origin.
    try:
        response = make_tracked_session(redact_values=(api_key,), allow_redirects=False).get(
            url, headers=_get_headers(api_key), timeout=10.0, allow_redirects=False
        )
    except Exception:  # noqa: BLE001 — a credential probe must never raise; any failure means "not validated"
        return False, "Could not reach the ElevenLabs API. Please try again."

    status = response.status_code
    if status == 200:
        return True, None
    if status == 403 or (status == 401 and _is_missing_permission(response)):
        if schema_name is None:
            return True, None
        return False, (
            f"Your ElevenLabs API key is missing the permission required to sync `{schema_name}`. "
            "Grant it on the key in your ElevenLabs account settings, then try again."
        )
    if status == 401:
        return False, _INVALID_API_KEY_MESSAGE
    # A 4xx other than the 401/403 above (a 400 is what users actually hit) is a deterministic client
    # error: the key was rejected and retrying sends the same request, so treat it as an invalid key
    # rather than a transient "try again". 429 is a rate limit and stays retryable below.
    if 400 <= status < 500 and status != 429:
        return False, _INVALID_API_KEY_MESSAGE
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

    partition_kwargs: dict[str, Any] = {}
    if config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [config.partition_key],
        }

    if config.fanout is not None:
        parent_config = ELEVENLABS_ENDPOINTS[config.fanout.parent_name]
        resource = cast(
            Resource,
            build_dependent_resource(
                # Both fan-out configs set page_size; only unpaginated endpoints leave it None.
                endpoint_configs=cast(Mapping[str, FanoutEndpointLike], ELEVENLABS_ENDPOINTS),
                child_endpoint=endpoint,
                fanout=config.fanout,
                client_config=_client_config(api_key, _paginator(config)),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
                # The server-side time filter is already in `params`, converted to Unix seconds.
                incremental_config_factory=lambda _field: None,
                parent_endpoint_extra={
                    "paginator": _paginator(parent_config),
                    "data_selector": parent_config.items_key,
                },
                child_endpoint_extra={"paginator": _paginator(config), "data_selector": config.items_key},
                child_params_extra=params,
                page_size_param=config.page_size_param,
            ),
        )
        if endpoint in SECRET_REDACTORS:
            resource.add_map(SECRET_REDACTORS[endpoint])
        return SourceResponse(
            name=endpoint,
            items=lambda: resource,
            primary_keys=config.primary_keys,
            sort_mode=config.sort_mode,  # type: ignore[arg-type]
            **partition_kwargs,
        )

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, _paginator(config)),
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
    if endpoint in SECRET_REDACTORS:
        resource.add_map(SECRET_REDACTORS[endpoint])

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,  # type: ignore[arg-type]
        **partition_kwargs,
    )
