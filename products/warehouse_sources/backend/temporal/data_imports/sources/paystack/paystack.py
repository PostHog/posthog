import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.paystack.settings import PAYSTACK_ENDPOINTS

PAYSTACK_BASE_URL = "https://api.paystack.co"
# Paystack caps list pages at 100 records (default 50).
PAGE_SIZE = 100


@dataclasses.dataclass
class PaystackResumeConfig:
    next_page: int


class PaystackPaginator(BasePaginator):
    """Page-number pagination over Paystack list endpoints.

    Paystack wraps list responses as ``{"status", "message", "data": [...], "meta": {...}}`` and
    paginates with ``page`` / ``perPage``. ``meta.pageCount`` reports the total number of pages, so
    we walk ``page`` from 1 until it exceeds ``pageCount``. When ``meta`` is missing (or carries no
    usable ``pageCount``) we fall back to stopping on the first empty page, which is Paystack's own
    recommended termination signal for offset pagination.
    """

    def __init__(self, page: int = 1) -> None:
        super().__init__()
        self._page = page

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["perPage"] = PAGE_SIZE
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


def get_resource(name: str) -> EndpointResource:
    config = PAYSTACK_ENDPOINTS[name]
    return {
        "name": name,
        "table_name": name.lower(),
        # Full refresh: Paystack offers no verified server-side updated-at filter, so we replace
        # the table each sync rather than risk a corrupt incremental watermark.
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": "data",
            "path": config.path,
        },
        "table_format": "delta",
    }


def paystack_source(
    secret_api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PaystackResumeConfig],
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": PAYSTACK_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": secret_api_key,
            },
            "paginator": PaystackPaginator(),
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"next_page": resume_config.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there's a next page to resume to; the Redis TTL handles cleanup.
        if state and state.get("next_page"):
            resumable_source_manager.save_state(PaystackResumeConfig(next_page=int(state["next_page"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        # Full refresh — no incremental cursor.
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


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
