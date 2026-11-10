from dataclasses import dataclass, field

from products.warehouse_sources.sources.sdk import IncrementalField


@dataclass(frozen=False)
class RssEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # True for endpoints that accept `page`/`limit` query params. The unpaginated endpoints return
    # the whole collection in a single response.
    paginated: bool = False
    # True for per-podcast endpoints (`{podcast_id}` in the path): the source iterates
    # `/podcasts` and queries the endpoint once per podcast, injecting `podcast_id` into every row.
    fan_out_podcasts: bool = False
    # True for per-episode endpoints (`{episode_id}` in the path): the source iterates every
    # podcast's episodes and queries the endpoint once per episode, injecting `podcast_id` and
    # `episode_id` into every row.
    fan_out_episodes: bool = False


# RSS.com Core API v4 list endpoints (https://api.rss.com/v4/docs). All are full-refresh only: the
# OpenAPI spec exposes no server-side timestamp filter (`updated_after`/`since`) on any list
# endpoint, so there is no incremental cursor to advance. `/v4/locations` is excluded — it is a
# search endpoint that requires a free-text `filter` string, not a listable collection.
RSS_ENDPOINTS: dict[str, RssEndpointConfig] = {
    "podcasts": RssEndpointConfig(name="podcasts", path="/podcasts"),
    "episodes": RssEndpointConfig(
        name="episodes",
        path="/podcasts/{podcast_id}/episodes",
        # The spec does not document episode ids as globally unique, so the injected parent id is
        # part of the key to keep it unique table-wide across the fan-out.
        primary_keys=["podcast_id", "id"],
        paginated=True,
        fan_out_podcasts=True,
    ),
    "categories": RssEndpointConfig(name="categories", path="/categories"),
    # Collaborator ids and keyword ids are not documented as globally unique either, so the parent
    # id is part of each per-podcast key.
    "collaborators": RssEndpointConfig(
        name="collaborators",
        path="/podcasts/{podcast_id}/collaborators",
        primary_keys=["podcast_id", "id"],
        fan_out_podcasts=True,
    ),
    "keywords": RssEndpointConfig(
        name="keywords",
        path="/podcasts/{podcast_id}/keywords",
        primary_keys=["podcast_id", "id"],
        fan_out_podcasts=True,
    ),
    "midrolls": RssEndpointConfig(
        name="midrolls",
        path="/podcasts/{podcast_id}/episodes/{episode_id}/midrolls",
        primary_keys=["podcast_id", "episode_id", "id"],
        fan_out_episodes=True,
    ),
}

ENDPOINTS = tuple(RSS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
