import re
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.aha.settings import (
    AHA_ENDPOINTS,
    PER_PAGE,
    AhaEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.jsonpath_utils import (
    find_values,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

AHA_API_PATH = "/api/v1"

# A single DNS label: letters, digits, hyphens. Rejects anything that could retarget the host
# (slashes, `@`, dots) so the stored API key is only ever sent to `<subdomain>.aha.io`.
_SUBDOMAIN_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


@dataclasses.dataclass
class AhaResumeConfig:
    # Next 1-indexed page to fetch. None means "start from page 1".
    next_page: int | None = None


def normalize_subdomain(subdomain: str) -> str:
    """Reduce user input to a bare, validated Aha! subdomain label.

    Accepts either the full host (``yourcompany.aha.io``) or the bare subdomain
    (``yourcompany``). Raises ``ValueError`` on anything that isn't a single DNS label so the
    API key can never be retargeted away from ``<subdomain>.aha.io``.
    """
    cleaned = subdomain.strip().removeprefix("https://").removeprefix("http://")
    cleaned = cleaned.strip("/")
    cleaned = cleaned.removesuffix(".aha.io")
    if not _SUBDOMAIN_RE.match(cleaned):
        raise ValueError(
            f"Invalid Aha! account domain: {subdomain!r}. Enter just your subdomain, e.g. 'yourcompany' "
            "for yourcompany.aha.io."
        )
    return cleaned


def _base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.aha.io{AHA_API_PATH}"


def _format_updated_since(value: Any) -> str:
    """Format an incremental cursor as the ISO8601 UTC string Aha! expects for `updated_since`."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _build_initial_params(
    config: AhaEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PER_PAGE}
    # Only Aha!'s `updated_since`-capable endpoints filter server-side; everything else is full refresh.
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value:
        params["updated_since"] = _format_updated_since(db_incremental_field_last_value)
    return params


class AhaPageNumberPaginator(PageNumberPaginator):
    """Page-number pagination with Aha!'s full-page fallback.

    Aha! reports `pagination.total_pages` (total number of PAGES), which the base paginator uses
    to stop after the last page. If that metadata is ever absent, fall back to the full-page
    heuristic: a short page means there are no more pages.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page or data is None:
            return
        try:
            values = find_values(self.total_path, response.json()) if self.total_path else []
        except Exception:
            values = []
        has_total_metadata = bool(values) and isinstance(values[0], int)
        if not has_total_metadata and len(data) < PER_PAGE:
            self._has_next_page = False


def aha_source(
    subdomain: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AhaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = AHA_ENDPOINTS[endpoint]
    params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(subdomain),
            # Auth (Bearer) goes through the framework auth config so its value is redacted from
            # logs; only the non-secret accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": AhaPageNumberPaginator(
                base_page=1,
                page_param="page",
                total_path="pagination.total_pages",
            ),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # A 200 body without the root key yields an empty page and ends pagination —
                    # same as the old implementation's `data.get(key, []) -> stop`.
                    "data_selector": config.response_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(AhaResumeConfig(next_page=int(state["page"])))

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
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(subdomain: str, api_key: str) -> tuple[bool, int | None]:
    """Probe Aha!'s `/me` endpoint to confirm the token is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error. Raises
    ``ValueError`` if the subdomain is malformed so the caller can surface a precise message.
    """
    url = f"{_base_url(subdomain)}/me"
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
