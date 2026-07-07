from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BunnyEndpointConfig:
    name: str
    path: str
    # bunny.net object IDs are globally unique within an account, so `Id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["Id"])
    # A stable (never-rewritten) datetime field to partition by. Only set where the object
    # actually exposes a creation timestamp — never `DateModified`, which changes on every edit.
    partition_key: Optional[str] = None


# bunny.net Core API list endpoints. All are full-refresh only: the list endpoints expose no
# server-side `updated_after`-style filter, so there is no genuine incremental cursor to advance
# (a client-side scan of every page would cost the same as a full refresh — see the skill).
BUNNY_ENDPOINTS: dict[str, BunnyEndpointConfig] = {
    "pull_zones": BunnyEndpointConfig(name="pull_zones", path="/pullzone"),
    "storage_zones": BunnyEndpointConfig(name="storage_zones", path="/storagezone"),
    "dns_zones": BunnyEndpointConfig(name="dns_zones", path="/dnszone", partition_key="DateCreated"),
    "video_libraries": BunnyEndpointConfig(name="video_libraries", path="/videolibrary", partition_key="DateCreated"),
}

ENDPOINTS = tuple(BUNNY_ENDPOINTS.keys())
