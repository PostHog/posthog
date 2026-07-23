import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlsplit

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.settings import (
    BETTER_STACK_BASE_URL,
    BETTER_STACK_ENDPOINTS,
    BetterStackEndpointConfig,
)
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


class BetterStackUntrustedURLError(Exception):
    pass


def _validate_pagination_url(url: str) -> str:
    """Pin every authenticated request to the Better Stack API origin.

    Both resumed `next_url` values (loaded from Redis) and upstream `pagination.next` URLs are
    followed verbatim with the customer's bearer token. Validating the scheme, host, and `/api/`
    path prefix keeps a poisoned resume state or a hostile upstream response from retargeting the
    request at another host and leaking the token (SSRF). Returns the URL unchanged when trusted.
    """
    parts = urlsplit(url)
    is_trusted = parts.scheme == "https" and parts.netloc == "uptime.betterstack.com" and parts.path.startswith("/api/")
    if not is_trusted:
        raise BetterStackUntrustedURLError(f"Refusing to follow pagination URL outside {BETTER_STACK_BASE_URL}/")
    return url


class BetterStackPaginator(JSONResponsePaginator):
    """Follows the response's `pagination.next` URL, refusing any URL off the Better Stack origin —
    whether it arrived in a response body or was seeded from saved resume state."""

    def __init__(self) -> None:
        super().__init__(next_url_path="pagination.next")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._next_url is not None:
            _validate_pagination_url(self._next_url)

    def set_resume_state(self, state: dict[str, Any]) -> None:
        super().set_resume_state(state)
        if self._next_url is not None:
            _validate_pagination_url(self._next_url)


@dataclasses.dataclass
class BetterStackResumeConfig:
    # Full next-page URL from the response's `pagination.next` field (null on the last page). It
    # carries the page, per_page, and any `from` filter, so following it preserves the incremental
    # window on every page.
    next_url: str | None = None


def _format_from_date(value: Any) -> str:
    """Format an incremental cursor value as the YYYY-MM-DD date the incidents `from` filter takes."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime/date cursor at now — asking for incidents newer than now is a no-op,
    so clamping keeps the filter sane if a future-dated record ever pushes the cursor forward."""
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _build_initial_params(
    config: BetterStackEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": config.page_size}

    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value:
        # The `from` filter is date-granular, so we re-fetch the watermark's whole day; merge on
        # the primary key dedupes the overlap.
        value = _clamp_future_value_to_now(db_incremental_field_last_value)
        params["from"] = _format_from_date(value)

    return params


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten a JSON:API resource object's `attributes` into the root and keep `id`/`type`."""
    flattened = {k: v for k, v in item.items() if k != "attributes"}
    attributes = item.get("attributes")
    if isinstance(attributes, dict):
        flattened.update(attributes)
    return flattened


def probe_credentials(api_token: str, endpoint: str | None = None) -> int | None:
    """Cheap probe of a Better Stack collection. Returns the HTTP status code, or None on a
    connection failure. Probes the given endpoint's path when set, else the monitors collection."""
    config = BETTER_STACK_ENDPOINTS.get(endpoint) if endpoint else None
    path = config.path if config else "/v2/monitors"
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(capture=False, redact_values=(api_token,)),
        f"{BETTER_STACK_BASE_URL}{path}?per_page=1",
        headers={"Authorization": f"Bearer {api_token}"},
    )
    return status


def better_stack_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BetterStackResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BETTER_STACK_ENDPOINTS[endpoint]

    params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BETTER_STACK_BASE_URL,
            # Auth (Bearer) goes through the framework auth config so its value is redacted from logs.
            "auth": {"type": "bearer", "token": api_token},
            # capture=False: incident `response_content` and monitor URLs can carry arbitrary
            # secrets the name-based scrubbers can't recognise, so keep them out of HTTP samples.
            "session": make_tracked_session(capture=False, redact_values=(api_token,)),
            "paginator": BetterStackPaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # A missing `data` key is treated as an empty page (matching the API's
                    # envelope, which always carries `data`), so no data_selector_required here.
                    "data_selector": "data",
                },
                # Better Stack is JSON:API — hoist each item's `attributes` into the row root.
                "data_map": _flatten_item,
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
            resumable_source_manager.save_state(BetterStackResumeConfig(next_url=state["next_url"]))

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
        # The incidents endpoint documents no sort param and its default ordering is unverified, so
        # declare "desc": the incremental watermark is committed once at the end of a successful
        # sync (safe for any arrival order) instead of checkpointed per batch.
        sort_mode="desc" if config.supports_incremental else "asc",
    )
