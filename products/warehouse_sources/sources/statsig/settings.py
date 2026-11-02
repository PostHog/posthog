from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://statsigapi.net"
API_VERSION = "20240601"
PAGE_SIZE = 100


@frozen
class StatsigEndpoint:
    path: str
    primary_key: str = "id"
    partition_key: str = "id"


ENDPOINTS: dict[str, StatsigEndpoint] = {
    "gates": StatsigEndpoint(path="/console/v1/gates"),
    "experiments": StatsigEndpoint(path="/console/v1/experiments"),
    "dynamic_configs": StatsigEndpoint(path="/console/v1/dynamic_configs"),
    "layers": StatsigEndpoint(path="/console/v1/layers"),
    "segments": StatsigEndpoint(path="/console/v1/segments"),
    "metrics": StatsigEndpoint(path="/console/v1/metrics/list"),
    "audit_logs": StatsigEndpoint(path="/console/v1/audit_logs"),
    "users": StatsigEndpoint(path="/console/v1/users", primary_key="userID", partition_key="userID"),
}

# Timestamp filters need live verification before they can safely control a sync watermark.
# Creation filters also miss changes to existing experiments, so metadata needs full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
