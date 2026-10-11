from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class WufooEndpointConfig:
    name: str
    # Path relative to https://<subdomain>.wufoo.com/api/v3 (includes the .json suffix).
    path: str
    # Top-level key in the JSON response that holds the list of records.
    data_key: str
    # Wufoo identifies every top-level object with a stable `Hash`, so it is a safe table-wide
    # primary key (forms, reports, and users all expose one).
    primary_keys: list[str] = field(default_factory=lambda: ["Hash"])


# Top-level Wufoo REST API v3 list endpoints. Per-form fan-out resources (a form's fields,
# entries, comments, widgets) require a parent form hash and are intentionally left out of this
# first cut — they can't be listed without first enumerating forms.
WUFOO_ENDPOINTS: dict[str, WufooEndpointConfig] = {
    "forms": WufooEndpointConfig(name="forms", path="forms.json", data_key="Forms"),
    "reports": WufooEndpointConfig(name="reports", path="reports.json", data_key="Reports"),
    "users": WufooEndpointConfig(name="users", path="users.json", data_key="Users"),
}

ENDPOINTS = tuple(WUFOO_ENDPOINTS.keys())

# Every endpoint is full refresh — Wufoo's account-level list endpoints expose no server-side
# `updated_after`-style cursor, so there is no genuine incremental field to advance.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
