from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

# Bluesky's public AppView (see `bluesky.py`). No auth is required for any of the endpoints below.
BASE_URL = "https://public.api.bsky.app"

ENDPOINTS = (
    "Profile",
    "Posts",
    "Followers",
    "Follows",
    "Likes",
    "Quotes",
)


@frozen
class PostFanoutEndpoint:
    path: str
    data_selector: str
    # Column the parent post's AT-URI lands in on each child row.
    parent_uri_column: str


# These tables call their endpoint once per post in the `Posts` feed, since both take a single post URI.
POST_FANOUT_ENDPOINTS: dict[str, PostFanoutEndpoint] = {
    "Likes": PostFanoutEndpoint(
        path="/xrpc/app.bsky.feed.getLikes", data_selector="likes", parent_uri_column="post_uri"
    ),
    "Quotes": PostFanoutEndpoint(
        path="/xrpc/app.bsky.feed.getQuotes", data_selector="posts", parent_uri_column="quoted_post_uri"
    ),
}

# None of these endpoints expose a server-side timestamp filter (e.g. `since`/`updated_after`) --
# they only support opaque cursor pagination -- so every table syncs as a full refresh. Per the
# incremental sync guidance, a client-side "stop when we've seen this id before" cursor would still
# walk every page on every run, so it isn't real incremental sync and isn't worth pretending here.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
