import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.paystack.settings import (
    PAYSTACK_ENDPOINTS,
    PaystackEndpointConfig,
)

PAYSTACK_BASE_URL = "https://api.paystack.co"
# Paystack caps list pages at 100 records (default 50).
PAGE_SIZE = 100


@dataclasses.dataclass(frozen=True)
class PaystackResumeConfig:
    next_page: Optional[int] = None
    next_cursor: Optional[str] = None
    # Fan-out tables checkpoint the shape the dependent resource emits: which parents finished
    # and where the current one stopped.
    fanout_state: Optional[dict[str, Any]] = None


class PaystackPaginator(BasePaginator):
    """Page-number pagination over Paystack list endpoints.

    Paystack wraps list responses as ``{"status", "message", "data": [...], "meta": {...}}`` and
    paginates with ``page`` / ``perPage``. ``meta.pageCount`` reports the total number of pages, so
    we walk ``page`` from 1 until it exceeds ``pageCount``. When ``meta`` is missing (or carries no
    usable ``pageCount``) we fall back to stopping on the first empty page, which is Paystack's own
    recommended termination signal for offset pagination.
    """

    def __init__(self, page: int = 1, page_size_param: str = "perPage") -> None:
        super().__init__()
        self._page = page
        self._page_size_param = page_size_param

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self._page_size_param] = PAGE_SIZE
        request.params["page"] = self._page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        meta: dict[str, Any] = {}
        try:
            body = response.json()
            if isinstance(body, dict) and isinstance(body.get("meta"), dict):
                meta = body["meta"]
        except Exception:
            meta = {}

        page_count = meta.get("pageCount")
        if isinstance(page_count, int):
            if self._page >= page_count:
                self._has_next_page = False
                return
        elif not data:
            self._has_next_page = False
            return

        self._page += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self._page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page:
            return {"next_page": self._page}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_page = state.get("next_page")
        if next_page is not None:
            self._page = int(next_page)
            self._has_next_page = True


def _build_paginator(config: PaystackEndpointConfig) -> BasePaginator:
    if config.cursor_paginated:
        return JSONResponseCursorPaginator(cursor_path="meta.next", cursor_param="cursor")
    return PaystackPaginator(page_size_param=config.page_size_param)


def get_resource(name: str) -> EndpointResource:
    config = PAYSTACK_ENDPOINTS[name]
    endpoint: Endpoint = {
        "data_selector": "data",
        "path": config.path,
        "paginator": _build_paginator(config),
    }
    resource: EndpointResource = {
        "name": name,
        "table_name": name.lower(),
        # Full refresh: Paystack offers no verified server-side updated-at filter, so we replace
        # the table each sync rather than risk a corrupt incremental watermark.
        "write_disposition": "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }
    if config.fanout is not None:
        endpoint["params"] = {
            config.fanout.resolve_param: {
                "type": "resolve",
                "resource": config.fanout.parent_name,
                "field": config.fanout.resolve_field,
            }
        }
        resource["include_from_parent"] = config.fanout.include_from_parent
    return resource


def _to_paginator_state(config: PaystackEndpointConfig, resume: PaystackResumeConfig) -> Optional[dict[str, Any]]:
    if config.fanout is not None:
        return resume.fanout_state
    if config.cursor_paginated:
        return {"cursor": resume.next_cursor} if resume.next_cursor else None
    return {"next_page": resume.next_page} if resume.next_page else None


def _to_resume_config(config: PaystackEndpointConfig, state: dict[str, Any]) -> Optional[PaystackResumeConfig]:
    if config.fanout is not None:
        return PaystackResumeConfig(fanout_state=state)
    if config.cursor_paginated:
        return PaystackResumeConfig(next_cursor=str(state["cursor"])) if state.get("cursor") else None
    return PaystackResumeConfig(next_page=int(state["next_page"])) if state.get("next_page") else None


def paystack_source(
    secret_api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PaystackResumeConfig],
) -> Resource:
    endpoint_config = PAYSTACK_ENDPOINTS[endpoint]
    resources: list[str | EndpointResource] = [get_resource(endpoint)]
    if endpoint_config.fanout is not None:
        resources.insert(0, get_resource(endpoint_config.fanout.parent_name))

    config: RESTAPIConfig = {
        "client": {
            "base_url": PAYSTACK_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": secret_api_key,
            },
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": resources,
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = _to_paginator_state(endpoint_config, resume_config)

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there's a next page to resume to; the Redis TTL handles cleanup.
        resume_config = _to_resume_config(endpoint_config, state) if state else None
        if resume_config is not None:
            resumable_source_manager.save_state(resume_config)

    if endpoint_config.fanout is None:
        return rest_api_resource(
            config,
            team_id,
            job_id,
            # Full refresh — no incremental cursor.
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )

    fanout = endpoint_config.fanout
    child = next(
        r
        for r in rest_api_resources(
            config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        if r.name == endpoint
    )
    return child.add_map(rename_parent_fields(fanout.parent_name, fanout.parent_field_renames))


def validate_credentials(secret_api_key: str) -> bool:
    """Cheap authenticated probe. A Paystack secret key is account-wide (no per-resource scopes),
    so a 200 on a 1-row transaction list confirms the key is genuine."""
    query = urlencode({"perPage": 1})
    res = make_tracked_session(redact_values=(secret_api_key,)).get(
        f"{PAYSTACK_BASE_URL}/transaction?{query}",
        headers={"Authorization": f"Bearer {secret_api_key}"},
        timeout=10,
    )
    return res.status_code == 200
