import dataclasses
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Response

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.hookdeck.settings import (
    HOOKDECK_API_HOST,
    HOOKDECK_ENDPOINTS,
    PAGE_SIZE,
    HookdeckEndpointConfig,
)


@dataclasses.dataclass
class HookdeckResumeConfig:
    # Opaque `pagination.next` cursor pointing at the page after the last one yielded.
    next_cursor: str


REDACTED = "***redacted***"

# Nested containers Hookdeck nests auth/verification secrets under. The whole value is masked:
# connections embed the full source and destination objects, so matching by container name reaches
# those embedded secrets at any depth without having to enumerate every per-type inner field.
_SECRET_CONTAINER_KEYS = frozenset({"auth", "auth_method", "verification"})

# Secret-bearing leaf keys that can sit directly in a destination/source config (e.g. an AWS or GCP
# destination) rather than inside one of the auth containers above. Curated to unambiguously
# credential names so non-secret fields on these rows survive.
_SECRET_LEAF_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "client_secret",
        "api_key",
        "apikey",
        "password",
        "secret_access_key",
        "access_key_id",
        "webhook_secret_key",
        "signing_secret",
        "private_key",
        "authorization",
    }
)


def _redact_secrets(value: Any) -> Any:
    """Mask credential-bearing fields in a Hookdeck row before it lands in a warehouse table.

    Destination auth, source verification and transformation `env` values are all secrets a reader
    of the resulting table would otherwise recover without holding the Hookdeck API key.
    """
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if item is None:
                redacted[key] = None
            elif lowered in _SECRET_CONTAINER_KEYS or lowered in _SECRET_LEAF_KEYS:
                redacted[key] = REDACTED
            elif lowered == "env" and isinstance(item, dict):
                # Transformation env names are user-chosen and not secret; only the values are.
                redacted[key] = dict.fromkeys(item, REDACTED)
            else:
                redacted[key] = _redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def _redact_pages(pages: Iterable[Any]) -> Iterator[Any]:
    for page in pages:
        yield [_redact_secrets(row) for row in page] if isinstance(page, list) else _redact_secrets(page)


def base_url(api_version: str) -> str:
    return f"{HOOKDECK_API_HOST}/{api_version}"


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as the ISO 8601 UTC string Hookdeck's date filters take."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        moment = datetime.combine(value, datetime.min.time())
    else:
        return str(value)

    utc_moment = moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
    return utc_moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def resolve_sort_field(config: HookdeckEndpointConfig, incremental_field: Optional[str]) -> str:
    """Pick the column used for both `order_by` and the `[gte]` filter.

    Falls back to the endpoint's first advertised incremental field when the stored selection isn't
    one Hookdeck can sort by, so the request sort can never disagree with the pipeline's watermark.
    """
    advertised = [entry["field"] for entry in config.incremental_fields]
    if incremental_field is not None and incremental_field in advertised:
        return incremental_field
    if advertised:
        return advertised[0]
    return config.default_order_by


def build_params(
    config: HookdeckEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: Optional[str],
) -> dict[str, Any]:
    incremental = should_use_incremental_field and bool(config.incremental_fields)
    sort_field = resolve_sort_field(config, incremental_field) if incremental else config.default_order_by

    params: dict[str, Any] = {
        "limit": PAGE_SIZE,
        "order_by": sort_field,
        # Oldest first so the watermark advances page by page. Hookdeck defaults to `desc`.
        "dir": "asc",
    }

    if incremental and db_incremental_field_last_value is not None:
        # Hookdeck date filters take either an ISO timestamp or an operator object rendered as
        # `field[gte]=...`. `gte` (not `gt`) re-reads the boundary row; merge dedupes it.
        params[f"{sort_field}[gte]"] = _format_datetime(db_incremental_field_last_value)

    return params


class HookdeckCursorPaginator(JSONResponseCursorPaginator):
    """Follows Hookdeck's opaque `pagination.next` cursor.

    Hookdeck documents "loop until no `next` is returned" but doesn't state whether the final page
    omits it, so an empty page or a cursor that doesn't advance also ends pagination rather than
    risk looping until the activity times out.
    """

    def __init__(self) -> None:
        super().__init__(cursor_path="pagination.next", cursor_param="next")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        previous_cursor = self._cursor_value
        super().update_state(response, data)

        if not self._has_next_page:
            return
        if data is not None and len(data) == 0:
            self._has_next_page = False
            return
        if previous_cursor is not None and self._cursor_value == previous_cursor:
            self._has_next_page = False


def validate_credentials(api_key: str, api_version: str) -> tuple[bool, int | None]:
    return validate_via_probe(
        # capture=False: the probe hits `/sources`, whose rows carry verification secrets the
        # name-based sample scrubbers don't recognise, so keep the response out of HTTP sample storage.
        lambda: make_tracked_session(redact_values=(api_key,), capture=False),
        f"{base_url(api_version)}/sources?limit=1",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )


def hookdeck_source(
    api_key: str,
    api_version: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HookdeckResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = HOOKDECK_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(api_version),
            # The API key rides the framework's bearer auth so it is redacted from logs and errors;
            # only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            # capture=False: raw responses reach the sampler before `_redact_pages` runs, and the
            # name-based scrubbers don't recognise Hookdeck's secret containers (`auth_method`,
            # `verification`, `env`) or raw inbound request payloads, so keep every response body
            # out of shared HTTP sample storage. Requests are still metered and logged (key redacted).
            "session": make_tracked_session(capture=False, redact_values=(api_key,)),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": build_params(
                        config,
                        should_use_incremental_field,
                        db_incremental_field_last_value,
                        incremental_field,
                    ),
                    "data_selector": "models",
                    "paginator": HookdeckCursorPaginator(),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"cursor": resume.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Called after each page is yielded, so a crash re-yields the last page (merge dedupes)
        # rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(HookdeckResumeConfig(next_cursor=str(state["cursor"])))

    # Incremental filtering is baked into the static params above, so the framework's own
    # incremental injection is unused.
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    # Endpoints whose rows embed auth/verification secrets get masked before the rows are written,
    # so a reader of the warehouse table can't recover credentials without the Hookdeck key.
    items = _redact_pages(resource) if config.contains_credentials else resource

    return SourceResponse(
        name=endpoint,
        items=lambda: items,
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Every request pins `dir=asc` on the same column the watermark tracks.
        sort_mode="asc",
    )
