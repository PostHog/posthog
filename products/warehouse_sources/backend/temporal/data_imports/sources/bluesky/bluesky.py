from collections.abc import Callable
from typing import Any, Optional
from urllib.parse import quote

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.settings import (
    BASE_URL,
    POST_FANOUT_ENDPOINTS,
    PostFanoutEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@frozen
class BlueskyResumeConfig:
    # Flat listings resume from the next page cursor.
    cursor: Optional[str] = None
    # Post fan-out tables resume from the state the fan-out checkpoints: which posts finished and
    # where the current one stopped.
    fanout_state: Optional[dict[str, Any]] = None


# Parent resource name for the post fan-out; child rows receive its fields as `_posts_<field>`.
_POSTS_PARENT = "posts"


def _cursor_paginator() -> JSONResponseCursorPaginator:
    # Bluesky returns the next cursor as a bare top-level `cursor` field (not nested, unlike the
    # `cursors.next` shape the paginator defaults to), echoed back as the `cursor` query param.
    return JSONResponseCursorPaginator(cursor_path="cursor", cursor_param="cursor")


def _posts_endpoint(actor: str) -> Endpoint:
    return {
        "path": "/xrpc/app.bsky.feed.getAuthorFeed",
        # `posts_no_replies` keeps this table to the author's own posts and reposts,
        # matching what most brand/marketing tracking cares about (own content, not
        # every reply the account has made).
        "params": {"actor": actor, "limit": 100, "filter": "posts_no_replies"},
        "data_selector": "feed[*].post",
        "paginator": _cursor_paginator(),
    }


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
            "endpoint": _posts_endpoint(actor),
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


def _add_encoded_uri(post: dict[str, Any]) -> dict[str, Any]:
    # The fan-out binds the parent field into the path with `str.format`, which applies no
    # escaping, and a did:web AT-URI can carry a percent-encoded port.
    post["encoded_uri"] = quote(post["uri"], safe="")
    return post


def _child_row_mapper(name: str, config: PostFanoutEndpoint) -> Callable[[dict[str, Any]], dict[str, Any]]:
    parent_key = f"_{_POSTS_PARENT}_uri"

    def _map(row: dict[str, Any]) -> dict[str, Any]:
        row[config.parent_uri_column] = row.pop(parent_key, None)
        if name == "Likes":
            # A like row has no id of its own, so the liker's DID keys it within the post.
            actor = row.get("actor") or {}
            row["actor_did"] = actor.get("did")
        return row

    return _map


def get_post_fanout_resources(name: str, actor: str) -> list[EndpointResource]:
    config = POST_FANOUT_ENDPOINTS[name]
    parent: EndpointResource = {
        "name": _POSTS_PARENT,
        "endpoint": _posts_endpoint(actor),
        "data_map": _add_encoded_uri,
    }
    child: EndpointResource = {
        "name": name,
        "table_name": name.lower(),
        "write_disposition": "replace",
        "table_format": "delta",
        "endpoint": {
            # The post URI rides in a query param; the resolve binding only substitutes into the path.
            "path": f"{config.path}?uri={{uri}}",
            "params": {
                "uri": {"type": "resolve", "resource": _POSTS_PARENT, "field": "encoded_uri"},
                "limit": 100,
            },
            "data_selector": config.data_selector,
            "paginator": _cursor_paginator(),
        },
        "include_from_parent": ["uri"],
        "data_map": _child_row_mapper(name, config),
    }
    return [parent, child]


def bluesky_source(
    actor: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BlueskyResumeConfig],
) -> Resource:
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if endpoint in POST_FANOUT_ENDPOINTS:
        fanout_config: RESTAPIConfig = {
            "client": {"base_url": BASE_URL},
            "resources": list(get_post_fanout_resources(endpoint, actor)),
        }

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(BlueskyResumeConfig(fanout_state=state))

        resources = rest_api_resources(
            fanout_config,
            team_id,
            job_id,
            db_incremental_field_last_value=None,
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=resume_config.fanout_state if resume_config else None,
        )
        return next(resource for resource in resources if resource.name == endpoint)

    config: RESTAPIConfig = {
        "client": {"base_url": BASE_URL},
        "resources": [get_resource(endpoint, actor)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume_config is not None and resume_config.cursor:
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
