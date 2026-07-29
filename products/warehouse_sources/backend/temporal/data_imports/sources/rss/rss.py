import dataclasses
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    AuthConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.rss.settings import RSS_ENDPOINTS

RSS_BASE_URL = "https://api.rss.com/v4"
# The episodes endpoint accepts a `limit` of up to 100 (default 100); the largest page minimises
# round trips.
PAGE_SIZE = 100
FIRST_PAGE = 1
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every endpoint.
DEFAULT_PROBE_PATH = "/podcasts"


@dataclasses.dataclass
class RssResumeConfig:
    """Resume state for the per-podcast episodes fan-out.

    `podcasts` and `categories` are single unpaginated requests, so only the episodes endpoint
    persists state. The framework fan-out now checkpoints into `fanout_state`; the legacy fields are
    kept (with defaults) only so state saved before the migration still parses
    (`ResumableSourceManager._load_json` does `dataclass(**saved)`). An old-shape bookmark restarts
    the fan-out from scratch — merge dedupes the re-pulled rows on the primary key.
    """

    # Legacy fan-out bookmark shape (pre-migration). Kept so old saved state still constructs.
    completed_podcast_ids: list[int] = dataclasses.field(default_factory=list)
    current_podcast_id: int | None = None
    next_page: int = FIRST_PAGE
    # Framework fan-out checkpoint: {"completed": [child_path, ...], "current": child_path | None,
    # "child_state": {"page": N} | None}.
    fanout_state: dict | None = None


class RssPageNumberPaginator(PageNumberPaginator):
    """Page-number paginator that also stops on a short page.

    RSS.com episode pages carry no total count; a page with fewer than `limit` rows is the last one,
    so stopping there saves the extra empty-page request the base paginator would otherwise pay. This
    mirrors the hand-rolled source's `len(items) < PAGE_SIZE` termination exactly.
    """

    def __init__(self, limit: int) -> None:
        super().__init__(base_page=FIRST_PAGE)
        self.limit = limit

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and data is not None and len(data) < self.limit:
            self._has_next_page = False


def _auth_config(api_key: str) -> AuthConfig:
    # Framework auth (not a hand-built header) so the key is redacted from logs/captured samples.
    return {"type": "api_key", "api_key": api_key, "name": "X-Api-Key", "location": "header"}


def _top_level_resource(endpoint: str, api_key: str, team_id: int, job_id: str) -> Resource:
    config = RSS_ENDPOINTS[endpoint]
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": RSS_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": _auth_config(api_key),
            # A single unpaginated request returns the whole collection.
            "paginator": SinglePagePaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # Every RSS.com list endpoint returns a bare JSON array; a 200 whose body isn't a
                    # list means an unexpected/transient payload — reissue it rather than syncing 0
                    # rows (the hand-rolled source raised a retryable error here).
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }
    return rest_api_resource(rest_config, team_id, job_id, None)


def _fan_out_episodes_resource(
    api_key: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[RssResumeConfig],
) -> Resource:
    config = RSS_ENDPOINTS["episodes"]
    parent_config = RSS_ENDPOINTS["podcasts"]

    # include_from_parent injects the parent's id under `_podcasts_id`; rename it to `podcast_id`
    # (kept as-is, no cast) so child rows keep the exact shape the hand-rolled source produced
    # (`{**item, "podcast_id": podcast_id}`). It's part of the composite primary key.
    prefixed_parent_id = f"_{parent_config.name}_id"

    def _inject_podcast_id(row: dict[str, Any]) -> dict[str, Any]:
        row["podcast_id"] = row.pop(prefixed_parent_id)
        return row

    parent_resource: EndpointResource = {
        "name": parent_config.name,
        "endpoint": {
            "path": parent_config.path,
            "paginator": SinglePagePaginator(),
            "data_selector_malformed_retryable": True,
        },
    }
    child_resource: EndpointResource = {
        "name": config.name,
        "include_from_parent": ["id"],
        "data_map": _inject_podcast_id,
        "endpoint": {
            "path": config.path,
            "params": {
                "podcast_id": {"type": "resolve", "resource": parent_config.name, "field": "id"},
                # `order=oldest` gives stable append-only ordering: episodes published mid-sync land
                # on the final pages instead of shifting every earlier page boundary by one.
                "order": "oldest",
                "limit": PAGE_SIZE,
            },
            "paginator": RssPageNumberPaginator(limit=PAGE_SIZE),
            # A bare JSON array is expected; a non-list body means the response shape changed —
            # fail loud instead of silently syncing 0 rows.
            "data_selector_required": True,
        },
    }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": RSS_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": _auth_config(api_key),
        },
        "resources": [parent_resource, child_resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        # Only a framework-shape checkpoint seeds the fan-out; an old-shape bookmark starts it fresh
        # and merge dedupes the re-pulled rows.
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            manager.save_state(RssResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(resource for resource in resources if resource.name == config.name)


def rss_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RssResumeConfig],
) -> SourceResponse:
    config = RSS_ENDPOINTS[endpoint]

    if config.fan_out_podcasts:
        resource = _fan_out_episodes_resource(api_key, team_id, job_id, resumable_source_manager)
    else:
        resource = _top_level_resource(endpoint, api_key, team_id, job_id)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # The API key is account-wide, so a single probe validates access to every endpoint. A bad key
    # 401/403s, a plan gap 402s. `redact_values` masks the key from any captured sample.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{RSS_BASE_URL}{DEFAULT_PROBE_PATH}",
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid RSS.com API key"
    if status == 402:
        return False, "The RSS.com API is only available on RSS.com Network plans. Upgrade your plan, then reconnect."
    if status is None:
        return False, "Could not validate RSS.com API key"
    return False, f"RSS.com returned HTTP {status}"
