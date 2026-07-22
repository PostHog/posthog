import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.settings import (
    CHURNKEY_BASE_URL,
    CHURNKEY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe


@dataclasses.dataclass
class ChurnkeyResumeConfig:
    # Offset (number of records to skip) for the next page to fetch. The API paginates via
    # `limit`/`skip`, so the offset is the only state we need to resume a full refresh.
    skip: int = 0


def _non_secret_headers(app_id: str) -> dict[str, str]:
    # The API key is supplied via the framework auth config so its value is redacted from logs;
    # only the non-secret app id / content negotiation headers are set here.
    return {
        "x-ck-app": app_id,
        "content-type": "application/json",
        "accept": "application/json",
    }


def validate_credentials(api_key: str, app_id: str) -> tuple[bool, Optional[int]]:
    """Probe the sessions endpoint with the smallest possible request.

    Returns ``(is_valid, status_code)``. A network failure surfaces as ``(False, None)``.
    """
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{CHURNKEY_BASE_URL}/sessions?limit=1",
        headers={"x-ck-api-key": api_key, **_non_secret_headers(app_id)},
    )


def churnkey_source(
    api_key: str,
    app_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ChurnkeyResumeConfig],
) -> SourceResponse:
    config = CHURNKEY_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CHURNKEY_BASE_URL,
            "headers": _non_secret_headers(app_id),
            "auth": {"type": "api_key", "api_key": api_key, "name": "x-ck-api-key", "location": "header"},
            # No total count anywhere in the response; termination is short/empty page.
            "paginator": OffsetPaginator(limit=config.page_size, offset_param="skip", total_path=None),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # The endpoint returns a bare JSON array — a non-list 200 body means the
                    # response shape changed, so fail loud instead of syncing garbage.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on `_id`) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(ChurnkeyResumeConfig(skip=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
