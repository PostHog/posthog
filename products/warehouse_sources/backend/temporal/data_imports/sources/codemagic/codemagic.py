import dataclasses
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.settings import BASE_URL, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@dataclasses.dataclass
class CodemagicResumeConfig:
    skip: int


class CodemagicBuildsPaginator(BasePaginator):
    """Skip-offset pagination for GET /builds.

    Codemagic doesn't document a page-size query param for this endpoint — only `skip` — so
    unlike `OffsetPaginator` we can't compare the page length against a declared limit to detect
    the last page (the vendor's actual fixed batch size isn't documented and could change without
    notice). Instead `skip` advances by however many rows the page actually returned, and
    pagination stops once a page comes back empty.
    """

    def __init__(self, skip: int = 0) -> None:
        super().__init__()
        self._skip = skip

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["skip"] = self._skip

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        self._skip += len(data)
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["skip"] = self._skip

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"skip": self._skip} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        skip = state.get("skip")
        if skip is not None:
            self._skip = int(skip)
            self._has_next_page = True


def get_resource(endpoint: str) -> EndpointResource:
    config = ENDPOINTS[endpoint]
    return {
        "name": config.name,
        "table_name": config.name.lower(),
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": config.data_selector,
            "path": config.path,
        },
        "table_format": "delta",
    }


def codemagic_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CodemagicResumeConfig],
) -> SourceResponse:
    endpoint_config = ENDPOINTS[endpoint]
    is_builds = endpoint == "Builds"
    paginator: BasePaginator = CodemagicBuildsPaginator() if is_builds else SinglePagePaginator()

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {
                "type": "api_key",
                "api_key": api_token,
                "name": "x-auth-token",
                "location": "header",
            },
            "paginator": paginator,
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if is_builds and resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"skip": resume_config.skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion. Saving happens after each page is yielded, so a crash re-fetches the last
        # page rather than skipping it.
        if state and state.get("skip") is not None:
            resumable_source_manager.save_state(CodemagicResumeConfig(skip=int(state["skip"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint if is_builds else None,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint_config.name.lower(),
        items=lambda: resource,
        primary_keys=["_id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        # Builds come back newest-first with no way to request ascending order; Applications is a
        # single unordered page where sort direction is moot.
        sort_mode="desc" if is_builds else "asc",
    )


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    response = make_tracked_session(redact_values=(api_token,)).get(
        f"{BASE_URL}/apps",
        headers={"x-auth-token": api_token},
    )
    if response.status_code == 200:
        return True, None
    return False, "Invalid Codemagic API token"
