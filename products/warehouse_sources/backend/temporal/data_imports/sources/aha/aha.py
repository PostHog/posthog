import re
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from requests import Response

from posthog.dataclasses import frozen

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.jsonpath_utils import (
    find_values,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

AHA_API_PATH = "/api/v1"

# A single DNS label: letters, digits, hyphens. Rejects anything that could retarget the host
# (slashes, `@`, dots) so the stored API key is only ever sent to `<subdomain>.aha.io`.
_SUBDOMAIN_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


@frozen
class AhaResumeConfig:
    # Top-level endpoints resume from the next 1-indexed page. None means "start from page 1".
    next_page: int | None = None
    # Fan-out endpoints (releases, requirements) resume by parent: the parent paths already fully
    # synced, the parent in progress, and that parent's paginator state — see
    # `common.rest_source.__init__._make_paginate_dependent_resource`.
    completed: list[str] | None = None
    current: str | None = None
    child_state: dict[str, Any] | None = None


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


def _client_config(subdomain: str, api_key: str) -> ClientConfig:
    return {
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
    }


def _incremental_window(field_name: str) -> IncrementalConfig:
    """Bind a fan-out child's cursor field to Aha!'s `updated_since` filter param."""
    return {
        "cursor_path": field_name,
        "start_param": "updated_since",
        "initial_value": "1970-01-01T00:00:00Z",
        "convert": _format_updated_since,
    }


def _make_source_response(config: AhaEndpointConfig, items: Any, column_hints: Any = None) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=column_hints,
    )


def _top_level_source(
    config: AhaEndpointConfig,
    subdomain: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AhaResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": _client_config(subdomain, api_key),
        "resource_defaults": {},
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

    return _make_source_response(config, lambda: resource, column_hints=resource.column_hints)


def _fanout_source(
    config: AhaEndpointConfig,
    subdomain: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AhaResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: str | None,
) -> SourceResponse:
    assert config.fanout is not None
    parent_config = AHA_ENDPOINTS[config.fanout.parent_name]

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and (resume.completed or resume.current):
            initial_state = {
                "completed": resume.completed or [],
                "current": resume.current,
                "child_state": resume.child_state,
            }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                AhaResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=AHA_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=_client_config(subdomain, api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
            incremental_config_factory=_incremental_window,
            # Aha! wraps every list response in a root key; select the array for parent and child.
            parent_endpoint_extra={"data_selector": parent_config.response_key},
            child_endpoint_extra={"data_selector": config.response_key},
            page_size_param="per_page",
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )

    return _make_source_response(config, lambda: dependent_resource)


def aha_source(
    subdomain: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AhaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = AHA_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(
            config,
            subdomain,
            api_key,
            endpoint,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
        )

    return _top_level_source(
        config,
        subdomain,
        api_key,
        endpoint,
        team_id,
        job_id,
        resumable_source_manager,
        should_use_incremental_field,
        db_incremental_field_last_value,
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
