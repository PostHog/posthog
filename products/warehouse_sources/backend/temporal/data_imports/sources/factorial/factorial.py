import dataclasses
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.factorial.settings import FACTORIAL_ENDPOINTS

# Factorial uses a single global host (no per-account subdomains) and dated, version-pinned paths.
# `2025-04-01` is a stable release within the currently supported version range; pinning avoids
# silently picking up breaking changes (resources occasionally move between groups across versions).
FACTORIAL_HOST = "https://api.factorialhr.com"
API_VERSION = "2025-04-01"
BASE_URL = f"{FACTORIAL_HOST}/api/{API_VERSION}"

# Factorial caps `limit` at 100 records per page across list endpoints (the default is also 100).
PAGE_SIZE = 100


@dataclasses.dataclass
class FactorialResumeConfig:
    # Opaque forward cursor (`meta.end_cursor`) passed back as `after_id` to fetch the next page.
    after_id: str


class FactorialCursorPaginator(BasePaginator):
    """Cursor paginator for Factorial's ``{"meta": {...}, "data": [...]}`` envelope.

    Factorial paginates forward by record id: each page returns a ``meta.end_cursor`` token that is
    passed back as ``after_id`` to fetch the next page, and ``meta.has_next_page`` signals when to
    stop. The cursor is an opaque (base64-encoded id) value, so we forward it verbatim. We also stop
    on an empty page as a backstop, so a misreported ``has_next_page`` can never loop us forever.
    """

    def __init__(self) -> None:
        super().__init__()
        self._after_id: Optional[str] = None

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["limit"] = PAGE_SIZE
        if self._after_id is not None:
            request.params["after_id"] = self._after_id

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        meta: dict[str, Any] = {}
        try:
            body = response.json()
            if isinstance(body, dict) and isinstance(body.get("meta"), dict):
                meta = body["meta"]
        except Exception:
            meta = {}

        end_cursor = meta.get("end_cursor")
        if not meta.get("has_next_page") or not end_cursor or not data:
            self._has_next_page = False
            self._after_id = None
            return

        self._after_id = str(end_cursor)
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        if self._after_id is not None:
            request.params["after_id"] = self._after_id

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._after_id is not None:
            return {"after_id": self._after_id}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        after_id = state.get("after_id")
        if after_id is not None:
            self._after_id = str(after_id)
            self._has_next_page = True


def get_resource(endpoint: str) -> EndpointResource:
    config = FACTORIAL_ENDPOINTS[endpoint]
    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": {
            # Every list endpoint wraps its records under a top-level `data` key.
            "data_selector": "data",
            "path": config.path,
            "params": {},
        },
        "table_format": "delta",
    }


def factorial_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FactorialResumeConfig],
) -> SourceResponse:
    endpoint_config = FACTORIAL_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            # Factorial authenticates with the account-wide `x-api-key` header. Going through
            # APIKeyAuth (rather than raw headers) registers the key for value-based log redaction.
            "auth": {
                "type": "api_key",
                "api_key": api_key,
                "name": "x-api-key",
                "location": "header",
            },
            "paginator": FactorialCursorPaginator(),
            "session": make_tracked_session(redact_values=(api_key,)),
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
            initial_paginator_state = {"after_id": resume_config.after_id}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there's a next page to resume to; the Redis TTL handles cleanup once the
        # sync finishes. Saving happens after each page is yielded, so a crash re-fetches the last
        # page rather than skipping it (merge dedupes the re-pulled rows on the primary key).
        if state and state.get("after_id"):
            resumable_source_manager.save_state(FactorialResumeConfig(after_id=str(state["after_id"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partition_key = endpoint_config.partition_key
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1 if partition_key else None,
        partition_size=1 if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="week" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
        # Cursor pagination walks records in ascending id order, so pages arrive in a stable,
        # forward-only sequence.
        sort_mode="asc",
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # Probe the core Employees resource: every HRIS account has it, and an API key with no access
    # would 401/403 here. Factorial API keys carry total account access, so there is no per-scope
    # nuance to accept at source-create time the way OAuth-scoped sources need.
    url = f"{BASE_URL}/resources/employees/employees"
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            url,
            params={"limit": 1},
            headers={"x-api-key": api_key},
            timeout=10,
            # `allow_redirects=False` as defense-in-depth — keeps the API key from being
            # forwarded to a redirected host even though the base URL is hard-coded.
            allow_redirects=False,
        )
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Factorial API key, or it does not have access to your account's data."
    return False, f"Factorial returned an unexpected status code: {response.status_code}"
