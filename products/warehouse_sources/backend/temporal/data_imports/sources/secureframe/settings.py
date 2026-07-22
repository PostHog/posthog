from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class SecureframeEndpointConfig:
    name: str
    path: str
    primary_key: str = "id"
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None


# Every list endpoint in the Secureframe public API paginates with `page`/`per_page`
# (per_page max 100) and wraps rows in JSON:API-style envelopes. The API exposes no
# server-side timestamp filter (only a Lucene `q` search whose date-range semantics are
# undocumented), so every endpoint is full refresh only.
SECUREFRAME_ENDPOINTS: dict[str, SecureframeEndpointConfig] = {
    "controls": SecureframeEndpointConfig(
        name="controls",
        path="/controls",
        partition_key="created_at",
    ),
    "tests": SecureframeEndpointConfig(
        name="tests",
        path="/tests",
        partition_key="created_at",
    ),
    "users": SecureframeEndpointConfig(
        name="users",
        path="/users",
        partition_key="created_at",
    ),
    "user_accounts": SecureframeEndpointConfig(
        name="user_accounts",
        path="/user_accounts",
        partition_key="created_at",
    ),
    "devices": SecureframeEndpointConfig(
        name="devices",
        path="/devices",
        partition_key="created_at",
    ),
    # The legacy vendor list. Its schema has no created_at, so no partitioning.
    "vendors": SecureframeEndpointConfig(
        name="vendors",
        path="/vendors",
    ),
    "tprm_vendors": SecureframeEndpointConfig(
        name="tprm_vendors",
        path="/tprm/vendors",
        partition_key="created_at",
    ),
    "frameworks": SecureframeEndpointConfig(
        name="frameworks",
        path="/frameworks",
        partition_key="created_at",
    ),
    "framework_requirements": SecureframeEndpointConfig(
        name="framework_requirements",
        path="/framework_requirements",
        partition_key="created_at",
    ),
    "risks": SecureframeEndpointConfig(
        name="risks",
        path="/risks",
        partition_key="created_at",
    ),
    "repositories": SecureframeEndpointConfig(
        name="repositories",
        path="/repositories",
        partition_key="created_at",
    ),
    # Integration connection schema exposes only id/name/status/vendor_name/updated_at.
    "integration_connections": SecureframeEndpointConfig(
        name="integration_connections",
        path="/integration_connections",
    ),
    "cloud_resources": SecureframeEndpointConfig(
        name="cloud_resources",
        path="/cloud_resources",
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(SECUREFRAME_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
