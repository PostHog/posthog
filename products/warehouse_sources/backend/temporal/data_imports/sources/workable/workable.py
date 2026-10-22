import re
import dataclasses
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponsePaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.workable.settings import (
    PAGE_SIZE,
    WORKABLE_ENDPOINTS,
    WorkableEndpointConfig,
)

# Workable account subdomains are DNS labels — letters, digits and hyphens. Validating this before
# building the URL prevents host injection (e.g. a `subdomain` of `evil.com/` would otherwise retarget
# the request and exfiltrate the stored token).
_SUBDOMAIN_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$")

# Maps the incremental cursor column to Workable's server-side time filter param. The column is
# `updated_at` / `created_at`; the filter is `updated_after` / `created_after`.
_TIME_FILTER_PARAM = {"updated_at": "updated_after", "created_at": "created_after"}


@dataclasses.dataclass(frozen=False)
class WorkableResumeConfig:
    # Full `paging.next` URL to fetch next. `None` means start the endpoint from its first page.
    next_url: str | None = None
    # Fan-out endpoints: the framework's dependent-resource resume state
    # (`{"completed": [...], "current": ..., "child_state": ...}`).
    fanout_state: dict[str, Any] | None = None


class WorkableOffsetPaginator(OffsetPaginator):
    """Advances `offset` by the rows a page returned rather than by the requested `limit`.

    Workable does not document a maximum `limit` for `/employees`, so a server-side cap below
    `PAGE_SIZE` would make the stock paginator skip rows or stop after the first short page.
    """

    def __init__(self, limit: int) -> None:
        super().__init__(limit=limit, total_path="totalCount")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return

        self.offset += len(data)
        body = response.json()
        total = body.get("totalCount") if isinstance(body, dict) else None
        self._has_next_page = not isinstance(total, int) or self.offset < total


def _validate_subdomain(subdomain: str) -> str:
    subdomain = (subdomain or "").strip()
    if not _SUBDOMAIN_RE.match(subdomain):
        raise ValueError(
            "Invalid Workable subdomain. Use just the account subdomain from "
            "https://<subdomain>.workable.com (letters, digits and hyphens only)."
        )
    return subdomain


def _base_url(subdomain: str) -> str:
    return f"https://{_validate_subdomain(subdomain)}.workable.com/spi/v3"


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as an ISO 8601 UTC timestamp with a `Z` suffix."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        return str(value)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sort_mode_for(endpoint: str, should_use_incremental_field: bool, incremental_field: str | None) -> SortMode:
    """Pick the order the pipeline should assume rows arrive in.

    Workable paginates by `since_id` (ascending id, which tracks ascending `created_at`); it has no
    way to sort by `updated_at`. So when the cursor field is `created_at`, rows genuinely arrive in
    ascending cursor order and the watermark can advance per batch (`asc`). When the cursor is
    `updated_at`, arrival order is unrelated to the cursor, so we use `desc` — which defers the
    watermark commit to sync completion — to avoid advancing past unsynced rows on a partial failure.
    """
    if not should_use_incremental_field or not WORKABLE_ENDPOINTS[endpoint].supports_incremental:
        return "asc"
    return "asc" if incremental_field == "created_at" else "desc"


def _incremental_config(field_name: str) -> IncrementalConfig:
    # `updated_after` / `created_after` are the documented filters; default to `updated_at` so edits
    # to existing rows are picked up. The value is formatted ISO 8601 with a `Z` suffix.
    filter_param = _TIME_FILTER_PARAM.get(field_name, "updated_after")
    return {"start_param": filter_param, "cursor_path": field_name, "convert": _format_datetime}


def _paginator(config: WorkableEndpointConfig) -> BasePaginator:
    if config.pagination == "offset":
        return WorkableOffsetPaginator(limit=config.page_size)
    if config.pagination == "none":
        return SinglePagePaginator()
    # `paging.next` is a full URL carrying the cursor params; the paginator follows it verbatim
    # and stops when it's absent.
    return JSONResponsePaginator(next_url_path="paging.next")


def _endpoint_extra(config: WorkableEndpointConfig) -> Endpoint:
    extra: Endpoint = {"paginator": _paginator(config)}
    # Rows are nested under the endpoint's data key (e.g. `{"jobs": [...]}`). A missing key
    # yields an empty page (matching the original `.get(data_key, [])`), so no fail-loud here.
    # Without a data key the body is the row array itself.
    if config.data_key is not None:
        extra["data_selector"] = config.data_key
    return extra


def _client_config(subdomain: str, api_token: str) -> ClientConfig:
    return {
        "base_url": _base_url(subdomain),
        # Auth (Bearer) goes through the framework auth config so the token is redacted from logs
        # and raised error messages; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_token},
        # Pin every request, including `paging.next` follow-ups and resume URLs, so a crafted next
        # link can't send the bearer token elsewhere. Workable's next links may point at
        # `www.workable.com/spi/v3/accounts/<subdomain>/...` rather than the account subdomain host.
        "allowed_hosts": ["www.workable.com"],
    }


def _fanout_items(
    config: WorkableEndpointConfig,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WorkableResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: str | None,
) -> Iterable[Any]:
    assert config.fanout is not None
    parent_config = WORKABLE_ENDPOINTS[config.fanout.parent_name]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(WorkableResumeConfig(fanout_state=state))

    # The parent candidate walk is never windowed: a new activity is not documented to move the
    # candidate's `updated_at`, so the time filter only applies to each candidate's activities.
    return build_dependent_resource(
        endpoint_configs=WORKABLE_ENDPOINTS,
        child_endpoint=config.name,
        fanout=config.fanout,
        client_config=client_config,
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=db_incremental_field_last_value,
        should_use_incremental_field=should_use_incremental_field and db_incremental_field_last_value is not None,
        incremental_field=incremental_field,
        incremental_config_factory=_incremental_config,
        parent_endpoint_extra=_endpoint_extra(parent_config),
        child_endpoint_extra=_endpoint_extra(config),
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def workable_source(
    subdomain: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WorkableResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = WORKABLE_ENDPOINTS[endpoint]
    client_config = _client_config(subdomain, api_token)

    if config.fanout is not None:
        fanout_items = _fanout_items(
            config,
            client_config,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value if should_use_incremental_field else None,
            incremental_field,
        )
        return _source_response(endpoint, config, fanout_items, should_use_incremental_field, incremental_field)

    params: dict[str, Any] = {"limit": PAGE_SIZE} if config.pagination == "next_url" else {}

    # Only inject the server-side time filter when the endpoint exposes one and we have a cursor to
    # filter on.
    incremental: Optional[IncrementalConfig] = None
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value is not None:
        incremental = _incremental_config(incremental_field or "updated_at")

    endpoint_config: Endpoint = {"path": config.path, "params": params}
    endpoint_config.update(_endpoint_extra(config))
    if incremental is not None:
        endpoint_config["incremental"] = incremental

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": endpoint_config,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(WorkableResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(endpoint, config, resource, should_use_incremental_field, incremental_field)


def _source_response(
    endpoint: str,
    config: WorkableEndpointConfig,
    resource: Iterable[Any],
    should_use_incremental_field: bool,
    incremental_field: str | None,
) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=_sort_mode_for(endpoint, should_use_incremental_field, incremental_field),
    )


def validate_credentials(subdomain: str, api_token: str, path: str = "/jobs") -> tuple[int, bool]:
    """Probe a Workable endpoint. Returns ``(status_code, ok)``; ``status_code`` is ``0`` on a transport error."""
    # Building the URL validates the subdomain and raises ValueError for an invalid one, before any
    # request — the caller surfaces that as a non-transport failure.
    url = f"{_base_url(subdomain)}{path}?{urlencode({'limit': 1})}"
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        url,
        headers=_get_headers(api_token),
    )
    return status or 0, ok
