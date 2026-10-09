import re
import dataclasses
from collections.abc import Callable, Iterable
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.settings import (
    LIGHTSPEED_RETAIL_ENDPOINTS,
    PAGE_SIZE,
)


@dataclasses.dataclass
class LightspeedRetailResumeConfig:
    # X-Series keyset pagination: `after=<version>` where version is the max
    # record version of the previous page — one integer fully describes where
    # to pick back up.
    after: Optional[int] = None
    # Fan-out endpoints checkpoint the `build_dependent_resource` shape instead: which parent
    # consignments finished and where the current one stopped.
    fanout_state: Optional[dict[str, Any]] = None


def _clean_domain_prefix(domain_prefix: str) -> str:
    """Accept either the bare store subdomain or a pasted full domain/URL."""
    prefix = domain_prefix.strip().removeprefix("https://").removeprefix("http://")
    prefix = prefix.split(".")[0].split("/")[0]
    if not re.fullmatch(r"[a-zA-Z0-9-]+", prefix):
        raise ValueError(f"Invalid Lightspeed domain prefix: {domain_prefix}")
    return prefix


def _base_url(domain_prefix: str, api_version: str) -> str:
    # X-Series carries the pinned vendor version as the `/api/<version>` path segment.
    return f"https://{_clean_domain_prefix(domain_prefix)}.retail.lightspeed.app/api/{api_version}"


def _to_version(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to an integer record version."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class LightspeedRetailPaginator(BasePaginator):
    """X-Series keyset pagination over the monotonic record `version`.

    The next page's `after` cursor is the max record version of the current page,
    read from the body's `version.max`. When that block is absent we recompute the
    max version from the page items; on the first page we still advance, but once a
    cursor exists a non-advancing fallback stops us rather than refetching the same
    window forever.
    """

    def __init__(self, after: Optional[int] = None) -> None:
        super().__init__()
        self._after = after

    def _apply_after(self, request: Request) -> None:
        if self._after is not None:
            if request.params is None:
                request.params = {}
            request.params["after"] = self._after

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume/incremental cursor on the first request.
        self._apply_after(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        items = data or []
        if not items:
            self._has_next_page = False
            return

        next_after = (response.json().get("version") or {}).get("max")
        if next_after is None:
            # Defensive: without the keyset cursor we can't advance; recompute
            # from the page to avoid refetching the same window forever.
            next_after = max((item.get("version") or 0) for item in items)
            if self._after is not None and next_after <= self._after:
                self._has_next_page = False
                return

        self._after = int(next_after)
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply_after(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._after is not None:
            return {"after": self._after}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        after = state.get("after")
        if after is not None:
            self._after = int(after)
            self._has_next_page = True


def lightspeed_retail_source(
    domain_prefix: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LightspeedRetailResumeConfig],
    api_version: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = LIGHTSPEED_RETAIL_ENDPOINTS[endpoint]

    client_config: ClientConfig = {
        "base_url": _base_url(domain_prefix, api_version),
        # Bearer auth via the framework so the token is redacted from logs and errors.
        "auth": {"type": "bearer", "token": api_token},
        "paginator": LightspeedRetailPaginator(),
    }

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.fanout is not None:

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(LightspeedRetailResumeConfig(fanout_state=state))

        child = build_dependent_resource(
            endpoint_configs=LIGHTSPEED_RETAIL_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=client_config,
            parent_endpoint_extra={"data_selector": "data"},
            child_endpoint_extra={"data_selector": "data"},
            page_size_param="page_size",
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=resume.fanout_state if resume else None,
        )
        return _source_response(endpoint, lambda: child)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"page_size": PAGE_SIZE},
                    # A missing `data` key is a legit empty page (stop), not an error.
                    "data_selector": "data",
                },
            }
        ],
    }

    # The version cursor doubles as the incremental watermark: on a resumed run seed
    # from saved state, otherwise (incremental) seed from the stored watermark.
    initial_after: Optional[int] = None
    if resume is not None:
        initial_after = resume.after
    elif should_use_incremental_field:
        initial_after = _to_version(db_incremental_field_last_value)

    initial_paginator_state: Optional[dict[str, Any]] = {"after": initial_after} if initial_after is not None else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded so a crash re-yields the last page (merge
        # dedupes on primary key) rather than skipping it.
        if state and state.get("after") is not None:
            resumable_source_manager.save_state(LightspeedRetailResumeConfig(after=int(state["after"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # incremental is applied via the paginator cursor, not a server-side param
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(endpoint, lambda: resource, resource.column_hints)


def _source_response(
    endpoint: str, items: Callable[[], Iterable[Any]], column_hints: Optional[dict[str, Any]] = None
) -> SourceResponse:
    config = LIGHTSPEED_RETAIL_ENDPOINTS[endpoint]
    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_key,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Keyset pagination on the monotonic version yields ascending version order.
        sort_mode="asc",
        column_hints=column_hints,
    )


def validate_credentials(domain_prefix: str, api_token: str, api_version: str) -> bool:
    """Confirm the token and store subdomain are valid with a cheap outlets probe."""
    try:
        url = f"{_base_url(domain_prefix, api_version)}/outlets?page_size=1"
    except ValueError:
        # A malformed domain prefix can't be validated — reject without a request.
        return False

    ok, _status = validate_via_probe(
        lambda: make_tracked_session(headers={"Authorization": f"Bearer {api_token}"}, redact_values=(api_token,)),
        url,
    )
    return ok
