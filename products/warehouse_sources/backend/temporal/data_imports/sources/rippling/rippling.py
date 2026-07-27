import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urljoin, urlsplit

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BaseNextUrlPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.settings import RIPPLING_ENDPOINTS

RIPPLING_BASE_URL = "https://rest.ripplingapis.com"
RIPPLING_HOST = urlsplit(RIPPLING_BASE_URL).netloc
# Rippling list pages cap at 100 items.
PAGE_SIZE = 100


@dataclasses.dataclass
class RipplingResumeConfig:
    # Rippling cursor pagination returns a `next_link` URL (sometimes relative);
    # we persist it absolutized, so it's all we need to pick back up.
    next_url: str


def _format_filter_timestamp(value: Any) -> str:
    """Format an incremental cursor for Rippling's OData-style filter (e.g. updated_at ge 2024-10-01T00:00:00)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00")
    return str(value)


def _build_params(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE}

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        cursor_field = incremental_field or "updated_at"
        params["filter"] = f"{cursor_field} ge {_format_filter_timestamp(db_incremental_field_last_value)}"
        # Ascending order on the cursor field so the incremental watermark
        # advances monotonically as pages are consumed (order_by defaults to asc).
        params["order_by"] = cursor_field
    else:
        # Full refresh: a stable creation-time sort prevents page-boundary
        # skips/duplicates if rows change mid-sync.
        params["order_by"] = "created_at"

    return params


def _absolutize_next_url(next_link: str) -> str:
    """Absolutize a pagination link against the Rippling host, rejecting off-domain targets.

    The session carries the user's bearer token in its default headers, so a malicious or
    buggy `next_link` pointing at another host could leak that token. Only https URLs on the
    Rippling API host (or relative paths resolving to it) are allowed."""
    next_url = urljoin(RIPPLING_BASE_URL, next_link)
    parts = urlsplit(next_url)
    if parts.scheme != "https" or parts.netloc != RIPPLING_HOST:
        raise ValueError(f"Rippling pagination link points off-domain: {next_link}")
    return next_url


def _build_url(path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{RIPPLING_BASE_URL}{path}"
    return f"{RIPPLING_BASE_URL}{path}?{urlencode(params)}"


class RipplingNextLinkPaginator(BaseNextUrlPaginator):
    """Follow Rippling's body-level `next_link` cursor.

    The link may be relative, so absolutize it against the API host (rejecting any off-domain
    or non-https target before the token-bearing request is sent). Resume is inherited from
    ``BaseNextUrlPaginator`` (``{"next_url": ...}``)."""

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            next_link = response.json().get("next_link")
        except Exception:
            next_link = None
        if next_link:
            self._next_url = _absolutize_next_url(next_link)
            self._has_next_page = True
        else:
            self._has_next_page = False


def validate_credentials(api_token: str) -> bool:
    """Confirm the API token is valid with a cheap one-company listing probe.

    Scoped tokens may lack individual dataset scopes (403); only 401 means the
    token itself is bad, so 403 is accepted at source-create time."""
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        _build_url("/companies", {"limit": 1}),
        headers={"Authorization": f"Bearer {api_token}"},
    )
    return status is not None and status != 401


def rippling_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RipplingResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = RIPPLING_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": RIPPLING_BASE_URL,
            # Auth (Bearer) via the framework config so the token is redacted from logs/errors.
            "auth": {"type": "bearer", "token": api_token},
            "paginator": RipplingNextLinkPaginator(),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": _build_params(
                        should_use_incremental_field, db_incremental_field_last_value, incremental_field
                    ),
                    # A missing `results` key is a legit empty page (not a fail-loud shape change).
                    "data_selector": "results",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(RipplingResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
        column_hints=resource.column_hints,
    )
