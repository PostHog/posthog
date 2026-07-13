from dataclasses import dataclass, field


@dataclass
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
}

ENDPOINTS = tuple(RSS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
