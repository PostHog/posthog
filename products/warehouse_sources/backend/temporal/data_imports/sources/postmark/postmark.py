"""Postmark (ActiveCampaign) transactional email source.

Postmark exposes a REST/JSON API at https://api.postmarkapp.com. Server-level resources
(messages, bounces, templates, message streams) authenticate with a per-server token sent
in the `X-Postmark-Server-Token` header.

Sync is full-refresh only. Postmark's list endpoints accept `fromdate`/`todate` filters
(date granularity, `YYYY-MM-DD`), but we have not been able to verify server-side filtering
against a live token, so we do not advertise incremental sync — matching how the existing
third-party connectors (Airbyte, Fivetran) treat Postmark. Within a sync, pagination is
resumable via the saved offset.

Two upstream constraints worth knowing about:
- The paginated list endpoints cap `count + offset` at 10,000, so a full refresh can only
  reach the most recent 10,000 rows of each. We log a warning when that window is hit.
- Messages expire from Postmark after a retention window (45 days by default), so historical
  data beyond that window is simply unavailable from the API.
"""

import logging
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
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.settings import (
    POSTMARK_ENDPOINTS,
    POSTMARK_MAX_PAGE_SIZE,
    POSTMARK_MAX_WINDOW,
)

logger = logging.getLogger(__name__)

POSTMARK_BASE_URL = "https://api.postmarkapp.com"


@dataclasses.dataclass
class PostmarkResumeConfig:
    # Offset of the next page to fetch on paginated list endpoints.
    next_offset: int = 0


class _WindowCappedOffsetPaginator(OffsetPaginator):
    """OffsetPaginator that warns when it stops because it hit Postmark's 10,000-row window.

    Postmark caps `count + offset` at 10,000 on its paginated list endpoints, so a full
    refresh can only reach the most recent 10,000 rows. `maximum_offset` handles the stop;
    this subclass adds the same diagnostic warning the hand-rolled loop emitted so an
    operator can see that older rows were left behind rather than silently dropped.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        # Only the maximum_offset boundary sets offset >= maximum_offset on stop; a short/empty
        # page stops with offset still below the window (see OffsetPaginator.update_state).
        if not self.has_next_page and self.maximum_offset is not None and self.offset >= self.maximum_offset:
            total: Any = None
            try:
                total = response.json().get("TotalCount")
            except Exception:
                pass
            logger.warning(
                f"Postmark: reached the {self.maximum_offset}-row API window (TotalCount={total}); "
                "older rows cannot be synced via this endpoint."
            )


def _get_headers(server_token: str) -> dict[str, str]:
    return {
        "X-Postmark-Server-Token": server_token,
        "Accept": "application/json",
    }


def validate_credentials(server_token: str) -> bool:
    # /message-streams is a cheap read-only call any valid server token can make. Postmark
    # returns 401 (ErrorCode 10) for an invalid/missing token and 200 otherwise.
    ok, _status = validate_via_probe(
        # `X-Postmark-Server-Token` is not in the sample-capture header denylist, so mask the
        # token by value to keep it out of any captured HTTP sample.
        lambda: make_tracked_session(redact_values=(server_token,)),
        f"{POSTMARK_BASE_URL}/message-streams",
        headers=_get_headers(server_token),
    )
    return ok


def postmark_source(
    server_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PostmarkResumeConfig],
) -> SourceResponse:
    config = POSTMARK_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    initial_paginator_state: Optional[dict[str, Any]] = None
    resume_hook = None

    if config.page_size is None:
        # Flat endpoints return their whole payload in a single response.
        paginator: Any = SinglePagePaginator()
    else:
        # Offset/count pagination capped at the 10,000-row API window. `count` is Postmark's
        # per-page size param; termination is a short/empty page or the window boundary.
        page_size = min(config.page_size, POSTMARK_MAX_PAGE_SIZE)
        paginator = _WindowCappedOffsetPaginator(
            limit=page_size,
            offset_param="offset",
            limit_param="count",
            total_path=None,
            maximum_offset=POSTMARK_MAX_WINDOW,
        )

        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if resume is not None:
                initial_paginator_state = {"offset": resume.next_offset}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; save AFTER a page is yielded so a crash
            # re-yields the last page (merge dedupes) rather than skipping it.
            if state and state.get("offset") is not None:
                resumable_source_manager.save_state(PostmarkResumeConfig(next_offset=int(state["offset"])))

        resume_hook = save_checkpoint

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": POSTMARK_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": {
                "type": "api_key",
                "api_key": server_token,
                "name": "X-Postmark-Server-Token",
                "location": "header",
            },
            "paginator": paginator,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # full refresh only — no incremental watermark
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
