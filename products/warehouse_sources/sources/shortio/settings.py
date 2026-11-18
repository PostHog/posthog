from products.warehouse_sources.sources.sdk import IncrementalField, frozen


@frozen
class ShortioEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]


SHORTIO_ENDPOINTS: dict[str, ShortioEndpointConfig] = {
    "domains": ShortioEndpointConfig(name="domains", path="/api/domains", primary_keys=["id"]),
    "links": ShortioEndpointConfig(name="links", path="/api/links?domain_id={domain_id}", primary_keys=["idString"]),
    "link_clicks": ShortioEndpointConfig(
        name="link_clicks",
        path="https://statistics.short.io/statistics/domain/{domain_id}/link_clicks?ids={link_id}",
        primary_keys=["domain_id", "link_id"],
    ),
    "last_clicks": ShortioEndpointConfig(
        name="last_clicks",
        path="https://statistics.short.io/statistics/domain/{domain_id}/last_clicks",
        # The API exposes no unique event ID. Timestamp and visitor fields can repeat.
        primary_keys=[],
    ),
    "link_by_interval": ShortioEndpointConfig(
        name="link_by_interval",
        path="https://statistics.short.io/statistics/link/{link_id}/by_interval",
        primary_keys=["domain_id", "link_id", "x"],
    ),
}

ENDPOINTS = tuple(SHORTIO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
