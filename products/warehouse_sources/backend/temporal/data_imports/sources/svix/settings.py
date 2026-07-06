from dataclasses import dataclass, field


@dataclass
class SvixEndpointConfig:
    name: str
    path: str
    # Primary key differs per endpoint: applications carry an opaque `id`, while event types are
    # keyed by their unique `name`.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Svix Management API top-level list endpoints. Both are cursor-paginated and full-refresh only —
# neither exposes a server-side updated-since filter, so there is no incremental cursor to advance.
# Per-application fan-out endpoints (endpoints, messages, message attempts) require an app id and
# are intentionally excluded from v1.
SVIX_ENDPOINTS: dict[str, SvixEndpointConfig] = {
    "applications": SvixEndpointConfig(name="applications", path="/app", primary_keys=["id"]),
    "event_types": SvixEndpointConfig(name="event_types", path="/event-type", primary_keys=["name"]),
}

ENDPOINTS = tuple(SVIX_ENDPOINTS.keys())
