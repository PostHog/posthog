from collections.abc import Iterator
from typing import Any, Optional

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
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@frozen
class BlueskyResumeConfig:
    # Flat listings resume from the next page cursor.
    cursor: Optional[str] = None
    # Post fan-out tables resume from a fixed-size position: the cursor of the feed page, the post
    # on that page to continue from, and that post's next child page. A list of finished posts
    # would grow with the account's history and be rewritten on every checkpoint.
    feed_cursor: Optional[str] = None
    post_uri: Optional[str] = None
    child_cursor: Optional[str] = None


def _cursor_paginator() -> JSONResponseCursorPaginator:
    # Bluesky returns the next cursor as a bare top-level `cursor` field (not nested, unlike the
    # `cursors.next` shape the paginator defaults to), echoed back as the `cursor` query param.
    return JSONResponseCursorPaginator(cursor_path="cursor", cursor_param="cursor")


_FEED_PATH = "/xrpc/app.bsky.feed.getAuthorFeed"
_FEED_DATA_SELECTOR = "feed[*].post"


def _feed_params(actor: str) -> dict[str, Any]:
    # `posts_no_replies` keeps this table to the author's own posts and reposts,
    # matching what most brand/marketing tracking cares about (own content, not
    # every reply the account has made).
    return {"actor": actor, "limit": 100, "filter": "posts_no_replies"}


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
                "path": _FEED_PATH,
                "params": _feed_params(actor),
                "data_selector": _FEED_DATA_SELECTOR,
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


def _fanout_row(endpoint: str, config: PostFanoutEndpoint, post_uri: str, row: dict[str, Any]) -> dict[str, Any]:
    row[config.parent_uri_column] = post_uri
    if endpoint == "Likes":
        # A like row has no id of its own, so the liker's DID keys it within the post.
        actor = row.get("actor") or {}
        row["actor_did"] = actor.get("did")
    return row


def _cursor_from_state(state: Optional[dict[str, Any]]) -> Optional[str]:
    cursor = (state or {}).get("cursor")
    return str(cursor) if cursor else None


def post_fanout_rows(
    actor: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[BlueskyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = POST_FANOUT_ENDPOINTS[endpoint]
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page_cursor = resume.feed_cursor if resume else None
    resume_post = resume.post_uri if resume else None
    resume_child_cursor = resume.child_cursor if resume else None
    # A repost of the account's own post puts the same post in the feed twice.
    seen: set[str] = set()

    next_feed: dict[str, Optional[str]] = {}
    next_child: dict[str, Optional[str]] = {}

    def remember_feed(state: Optional[dict[str, Any]], has_next: bool) -> None:
        next_feed["cursor"] = _cursor_from_state(state)

    def remember_child(state: Optional[dict[str, Any]], has_next: bool) -> None:
        next_child["cursor"] = _cursor_from_state(state)

    client = RESTClient(base_url=BASE_URL)
    try:
        for posts in client.paginate(
            path=_FEED_PATH,
            params=_feed_params(actor),
            paginator=_cursor_paginator(),
            data_selector=_FEED_DATA_SELECTOR,
            initial_paginator_state={"cursor": page_cursor} if page_cursor else None,
            page_state_hook=remember_feed,
        ):
            next_page_cursor = next_feed.get("cursor")
            uris = [post["uri"] for post in posts]
            start = uris.index(resume_post) if resume_post in uris else 0
            for index in range(start, len(uris)):
                uri = uris[index]
                if uri in seen:
                    continue
                seen.add(uri)

                if index + 1 < len(uris):
                    after_post: Optional[BlueskyResumeConfig] = BlueskyResumeConfig(
                        feed_cursor=page_cursor, post_uri=uris[index + 1]
                    )
                elif next_page_cursor:
                    after_post = BlueskyResumeConfig(feed_cursor=next_page_cursor)
                else:
                    after_post = None

                child_cursor = resume_child_cursor if uri == resume_post else None
                for rows in client.paginate(
                    path=config.path,
                    params={"uri": uri, "limit": 100},
                    paginator=_cursor_paginator(),
                    data_selector=config.data_selector,
                    initial_paginator_state={"cursor": child_cursor} if child_cursor else None,
                    page_state_hook=remember_child,
                ):
                    if next_child.get("cursor"):
                        resumable_source_manager.save_state(
                            BlueskyResumeConfig(
                                feed_cursor=page_cursor, post_uri=uri, child_cursor=next_child["cursor"]
                            )
                        )
                    elif after_post is not None:
                        resumable_source_manager.save_state(after_post)

                    if rows:
                        yield [_fanout_row(endpoint, config, uri, row) for row in rows]
                    else:
                        resumable_source_manager.safe_point()

            resume_post = None
            resume_child_cursor = None
            page_cursor = next_page_cursor
            resumable_source_manager.safe_point()
    finally:
        client.session.close()


def bluesky_source(
    actor: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BlueskyResumeConfig],
) -> Resource:
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

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
