import dataclasses
from typing import Any, Optional

from requests import Request, Response
from requests.exceptions import RequestException

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.settings import WORKOS_ENDPOINTS

BASE_URL = "https://api.workos.com"


@dataclasses.dataclass
class WorkOSResumeConfig:
    """Resume state for WorkOS endpoints.

    Every WorkOS list endpoint uses cursor pagination keyed on the ``after``
    object ID returned in ``list_metadata.after``. The checkpoint is just that
    cursor. On resume we start fetching from the saved cursor (at-least-once
    semantics): the page whose cursor did not persist before a crash is
    re-yielded and deduped by the ``id`` primary key.
    """

    after: str


class WorkOSPaginator(BasePaginator):
    """Cursor paginator for the WorkOS API.

    WorkOS returns ``{"data": [...], "list_metadata": {"before": ..., "after": ...}}``.
    The next page is fetched by passing ``after=<last object id>``; pagination
    ends when ``list_metadata.after`` is null.
    """

    def __init__(self) -> None:
        super().__init__()
        self._after: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Emit the seeded cursor on the first request so resume starts from the
        # saved page. Fresh runs (no cursor) omit the param.
        if self._after is not None:
            if request.params is None:
                request.params = {}
            request.params["after"] = self._after

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        try:
            body = response.json()
        except ValueError:
            body = None

        next_after = None
        if isinstance(body, dict):
            metadata = body.get("list_metadata")
            if isinstance(metadata, dict):
                next_after = metadata.get("after")

        if next_after:
            self._after = next_after
            self._has_next_page = True
        else:
            self._after = None
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._has_next_page and self._after is not None:
            if request.params is None:
                request.params = {}
            request.params["after"] = self._after

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # ``_after`` retains the previous page's cursor once exhausted, so guard on
        # ``_has_next_page`` to avoid handing back a stale checkpoint that would
        # re-fetch an already-processed page on resume.
        if not self._has_next_page or self._after is None:
            return None
        return {"after": self._after}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        after = state.get("after")
        if after:
            self._after = after
            self._has_next_page = True


def get_resource(name: str) -> EndpointResource:
    config = WORKOS_ENDPOINTS[name]

    endpoint_config: Endpoint = {
        "path": config.path,
        "data_selector": "data",
        "params": {
            "limit": config.page_size,
            # Stable creation-ordered pagination so the cursor walks deterministically.
            # Must be "desc" (the WorkOS SDK default): the high-volume directory_users
            # and directory_groups list endpoints reject "order=asc" with a 422, while
            # "desc" is accepted on every WorkOS list endpoint.
            "order": "desc",
        },
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Validate WorkOS API credentials with a cheap list call."""
    url = f"{BASE_URL}/organizations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = make_tracked_session().get(url, headers=headers, params={"limit": 1}, timeout=10)

        if response.status_code == 200:
            return True, None

        # A valid key that lacks the Organizations scope still proves the key is
        # genuine — accept it at source-create so users can sync only the
        # endpoints they granted. Sync-time 403s are handled by
        # get_non_retryable_errors().
        if response.status_code == 403:
            return True, None

        if response.status_code == 401:
            return False, "Your WorkOS API key is invalid or has been revoked."

        try:
            error_data = response.json()
            message = error_data.get("message")
            if message:
                return False, message
        except ValueError:
            pass

        return False, response.text
    except RequestException as e:
        return False, str(e)


def workos_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WorkOSResumeConfig],
) -> SourceResponse:
    endpoint_config = WORKOS_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {
                "Content-Type": "application/json",
            },
            "paginator": WorkOSPaginator(),
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    # Seed the paginator from the saved checkpoint when resuming.
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.after:
            initial_paginator_state = {"after": resume_config.after}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # rest_client passes None once the paginator is exhausted; nothing to persist then.
        if state and state.get("after"):
            resumable_source_manager.save_state(WorkOSResumeConfig(after=str(state["after"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[endpoint_config.partition_key],
    )
