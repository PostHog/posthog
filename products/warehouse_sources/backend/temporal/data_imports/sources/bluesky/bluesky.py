from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.settings import BASE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@frozen
class BlueskyResumeConfig:
    cursor: str


def _cursor_paginator() -> JSONResponseCursorPaginator:
    # Bluesky returns the next cursor as a bare top-level `cursor` field (not nested, unlike the
    # `cursors.next` shape the paginator defaults to), echoed back as the `cursor` query param.
    return JSONResponseCursorPaginator(cursor_path="cursor", cursor_param="cursor")


def get_resource(name: str, actor: str) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "Profile": {
            "name": "Profile",
            "table_name": "profile",
            "write_disposition": "replace",
            "table_format": "delta",
            "endpoint": {
                "path": "/xrpc/app.bsky.actor.getProfile",
                "params": {"actor": actor},
                "data_selector": "$",
                "paginator": SinglePagePaginator(),
            },
        },
        "Posts": {
            "name": "Posts",
            "table_name": "posts",
            "write_disposition": "replace",
            "table_format": "delta",
            "endpoint": {
                "path": "/xrpc/app.bsky.feed.getAuthorFeed",
                # `posts_no_replies` keeps this table to the author's own posts and reposts,
                # matching what most brand/marketing tracking cares about (own content, not
                # every reply the account has made).
                "params": {"actor": actor, "limit": 100, "filter": "posts_no_replies"},
                "data_selector": "feed[*].post",
                "paginator": _cursor_paginator(),
            },
        },
        "Followers": {
            "name": "Followers",
            "table_name": "followers",
            "write_disposition": "replace",
            "table_format": "delta",
            "endpoint": {
                "path": "/xrpc/app.bsky.graph.getFollowers",
                "params": {"actor": actor, "limit": 100},
                "data_selector": "followers",
                "paginator": _cursor_paginator(),
            },
        },
        "Follows": {
            "name": "Follows",
            "table_name": "follows",
            "write_disposition": "replace",
            "table_format": "delta",
            "endpoint": {
                "path": "/xrpc/app.bsky.graph.getFollows",
                "params": {"actor": actor, "limit": 100},
                "data_selector": "follows",
                "paginator": _cursor_paginator(),
            },
        },
    }
    return resources[name]


def bluesky_source(
    actor: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BlueskyResumeConfig],
) -> Resource:
    config: RESTAPIConfig = {
        "client": {"base_url": BASE_URL},
        "resources": [get_resource(endpoint, actor)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion, and the single-page Profile endpoint never produces a cursor here.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(BlueskyResumeConfig(cursor=str(state["cursor"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(actor: str) -> tuple[bool, str | None]:
    session = make_tracked_session()
    response = session.get(f"{BASE_URL}/xrpc/app.bsky.actor.getProfile", params={"actor": actor})
    if response.status_code == 200:
        return True, None

    try:
        message = response.json().get("message")
    except ValueError:
        message = None

    if response.status_code == 400:
        return False, message or "That handle or DID couldn't be found on Bluesky. Check the spelling and try again."
    return False, message or f"Bluesky returned an unexpected error ({response.status_code})."
