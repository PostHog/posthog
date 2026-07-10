from dataclasses import dataclass, field


@dataclass
class MyHoursEndpointConfig:
    name: str
    path: str
    # My Hours object IDs are unique within an account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# My Hours REST API list endpoints. All are full-refresh only: the API exposes no row-level
# pagination and no updated-since cursor, so there is no incremental cursor to advance. The
# per-user activity report (`Reports/activity`) is intentionally excluded — it requires a
# mandatory `DateFrom`/`DateTo` window rather than being a plain top-level list.
MY_HOURS_ENDPOINTS: dict[str, MyHoursEndpointConfig] = {
    "clients": MyHoursEndpointConfig(name="clients", path="/Clients"),
    "projects": MyHoursEndpointConfig(name="projects", path="/Projects/getAll"),
    "tags": MyHoursEndpointConfig(name="tags", path="/Tags"),
    "users": MyHoursEndpointConfig(name="users", path="/Users/getAll"),
}

ENDPOINTS = tuple(MY_HOURS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
