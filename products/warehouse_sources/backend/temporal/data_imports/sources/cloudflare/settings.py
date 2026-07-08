from dataclasses import dataclass
from typing import Optional


@dataclass
class CloudflareEndpointConfig:
    name: str
    # Path under https://api.cloudflare.com/client/v4; `{zone_id}` is
    # substituted during the per-zone fan-out.
    path: str
    primary_key: str = "id"
    # Fan-out parent (today only zones).
    zone_scoped: bool = False
    # Field injected to keep the parent linkage on fan-out rows.
    parent_key: Optional[str] = None


# Cloudflare's v4 REST lists have no updated-since filters and are small
# configuration tables, so every stream is a full refresh. The high-volume
# analytics datasets live in the separate GraphQL API — a follow-up.
CLOUDFLARE_ENDPOINTS: dict[str, CloudflareEndpointConfig] = {
    "accounts": CloudflareEndpointConfig(
        name="accounts",
        path="/accounts",
    ),
    "zones": CloudflareEndpointConfig(
        name="zones",
        path="/zones",
    ),
    "dns_records": CloudflareEndpointConfig(
        name="dns_records",
        path="/zones/{zone_id}/dns_records",
        zone_scoped=True,
        parent_key="_zone_id",
    ),
}

ENDPOINTS = tuple(CLOUDFLARE_ENDPOINTS.keys())
