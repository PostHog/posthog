import dataclasses
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.settings import (
    HUGGING_FACE_ENDPOINTS,
    HuggingFaceEndpointConfig,
)

HUGGING_FACE_BASE_URL = "https://huggingface.co"

# The Hub caps list endpoints at 1000 rows per page; larger pages don't return more.
PAGE_SIZE = 1000


@dataclasses.dataclass
class HuggingFaceResumeConfig:
    # URL of the page to resume from. We checkpoint the *next* page's self-contained Link-header URL
    # after a page is yielded, so a resumed run continues from where it left off (already-yielded
    # pages are persisted before the checkpoint; the delta merge dedupes on the primary key).
    resume_url: str


class HuggingFaceLinkPaginator(HeaderLinkPaginator):
    """Follows the Hub's ``Link: <…>; rel="next"`` cursor, but also stops on an empty page.

    The Hub omits the next link once it runs out of rows, but we terminate on an empty page even if a
    stray next link is present — matching the original source's "empty page ends the stream" guard and
    avoiding an unbounded loop.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)


def hugging_face_source(
    api_token: str,
    endpoint: str,
    author: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HuggingFaceResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = HUGGING_FACE_ENDPOINTS[endpoint]
    params = _build_initial_params(config, author)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": HUGGING_FACE_BASE_URL,
            # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
            # logs and raised errors; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_token},
            "paginator": HuggingFaceLinkPaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.resume_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a resumed run picks
        # up at the next self-contained Link-header URL.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(HuggingFaceResumeConfig(resume_url=state["next_url"]))

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
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        column_hints=resource.column_hints,
    )


def validate_credentials(api_token: str) -> bool:
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{HUGGING_FACE_BASE_URL}/api/whoami-v2",
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
    )
    return ok


def _build_initial_params(config: HuggingFaceEndpointConfig, author: str) -> dict[str, Any]:
    # Sort ascending by createdAt (immutable), so new repos append to the end and don't shift pages
    # we've already walked mid-sync. The Hub has no server-side timestamp range filter, so these
    # endpoints are full refresh only.
    params: dict[str, Any] = {"author": author, "sort": "createdAt", "direction": 1, "limit": PAGE_SIZE}
    if config.full:
        params["full"] = "true"
    return params
