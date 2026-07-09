import dataclasses
from typing import Any, Optional

from requests import Request
from requests.exceptions import RequestException

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.lingo_dev.settings import (
    LINGO_DEV_BASE_URL,
    LINGO_DEV_ENDPOINTS,
)


@dataclasses.dataclass
class LingoDevResumeConfig:
    """Resume state for Lingo.dev endpoints.

    Lingo.dev paginates with an opaque ``nextCursor`` token that marks a position in the
    result stream, so the checkpoint is just the cursor of the next unfetched page. On
    resume we start fetching from the saved cursor (at-least-once semantics): duplicates
    from a batch that was yielded but whose checkpoint did not persist are deduped by the
    ``id`` primary key.
    """

    cursor: str


class LingoDevPaginator(JSONResponseCursorPaginator):
    """Cursor paginator for Lingo.dev: ``?cursor=`` request param, ``nextCursor`` in the
    response body (``null`` on the last page)."""

    def __init__(self) -> None:
        super().__init__(cursor_path="nextCursor", cursor_param="cursor")

    def init_request(self, request: Request) -> None:
        # Emit the seeded cursor on the first request so a resumed run starts at the
        # saved page rather than the beginning of the stream.
        if self._cursor_value:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor_value

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # rest_client only calls this when has_next_page is True, so ``_cursor_value``
        # already points at the next unfetched page.
        if self._cursor_value:
            return {"cursor": self._cursor_value}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor:
            self._cursor_value = str(cursor)
            self._has_next_page = True


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    url = f"{LINGO_DEV_BASE_URL}/jobs/localization"
    headers = {"X-API-Key": api_key}

    try:
        response = make_tracked_session().get(url, headers=headers, params={"limit": 1}, timeout=10)

        if response.status_code == 200:
            return True, None

        # Errors come back as {"_tag": "UnauthorizedError", "message": "Invalid API key"}
        try:
            error_data = response.json()
            message = error_data.get("message")
            if isinstance(message, str) and message:
                return False, message
        except Exception:
            pass

        return False, response.text
    except RequestException as e:
        return False, str(e)


def get_resource(name: str) -> EndpointResource:
    config = LINGO_DEV_ENDPOINTS[name]

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": {"limit": config.page_size},
        # Responses are wrapped as {"items": [...], "nextCursor": "..."}
        "data_selector": "items",
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def lingo_dev_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LingoDevResumeConfig],
) -> SourceResponse:
    endpoint_config = LINGO_DEV_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": LINGO_DEV_BASE_URL,
            "headers": {
                "X-API-Key": api_key,
                "Content-Type": "application/json",
            },
            "paginator": LingoDevPaginator(),
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
        if resume_config is not None and resume_config.cursor:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # rest_client passes None once the paginator is exhausted; nothing to persist then.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(LingoDevResumeConfig(cursor=str(state["cursor"])))

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
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[endpoint_config.partition_key],
        # /jobs/localization returns jobs newest-first and the cursor cannot reverse it.
        sort_mode="desc",
    )
