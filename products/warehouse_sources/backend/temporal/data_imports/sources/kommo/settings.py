from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Kommo caps every list endpoint at 250 entities per response.
PAGE_LIMIT = 250

API_BASE_PATH = "/api/v4"


@dataclass(frozen=True)
class KommoEndpoint:
    path: str
    data_selector: str
    primary_key: list[str]
    # Server-side lower-bound filter for incremental syncs, e.g. `filter[updated_at][from]`.
    # None means the endpoint is full refresh only.
    incremental_param: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    # Endpoints that return their whole collection in one unpaginated response.
    paginated: bool = True


# `order[updated_at]=asc` is set on every endpoint that documents it, so rows arrive in the
# same order the incremental watermark advances in. Tasks and Events are deliberately full
# refresh: both expose a server-side timestamp filter, but neither documents an ordering
# parameter for that timestamp, and an unordered incremental sync silently corrupts the
# watermark. Tasks still asks for `order[created_at]=asc` so pagination is at least stable.
ENDPOINT_CONFIG: dict[str, KommoEndpoint] = {
    "Leads": KommoEndpoint(
        path=f"{API_BASE_PATH}/leads",
        data_selector="_embedded.leads",
        primary_key=["id"],
        incremental_param="filter[updated_at][from]",
        params={"with": "contacts,loss_reason,source", "order[updated_at]": "asc"},
    ),
    "Contacts": KommoEndpoint(
        path=f"{API_BASE_PATH}/contacts",
        data_selector="_embedded.contacts",
        primary_key=["id"],
        incremental_param="filter[updated_at][from]",
        params={"with": "leads", "order[updated_at]": "asc"},
    ),
    "Companies": KommoEndpoint(
        path=f"{API_BASE_PATH}/companies",
        data_selector="_embedded.companies",
        primary_key=["id"],
        incremental_param="filter[updated_at][from]",
        params={"with": "contacts,leads", "order[updated_at]": "asc"},
    ),
    "LeadNotes": KommoEndpoint(
        path=f"{API_BASE_PATH}/leads/notes",
        data_selector="_embedded.notes",
        primary_key=["id"],
        incremental_param="filter[updated_at][from]",
        params={"order[updated_at]": "asc"},
    ),
    "ContactNotes": KommoEndpoint(
        path=f"{API_BASE_PATH}/contacts/notes",
        data_selector="_embedded.notes",
        primary_key=["id"],
        incremental_param="filter[updated_at][from]",
        params={"order[updated_at]": "asc"},
    ),
    "CompanyNotes": KommoEndpoint(
        path=f"{API_BASE_PATH}/companies/notes",
        data_selector="_embedded.notes",
        primary_key=["id"],
        incremental_param="filter[updated_at][from]",
        params={"order[updated_at]": "asc"},
    ),
    "Tasks": KommoEndpoint(
        path=f"{API_BASE_PATH}/tasks",
        data_selector="_embedded.tasks",
        primary_key=["id"],
        params={"order[created_at]": "asc"},
    ),
    "Events": KommoEndpoint(
        path=f"{API_BASE_PATH}/events",
        data_selector="_embedded.events",
        primary_key=["id"],
    ),
    "Pipelines": KommoEndpoint(
        path=f"{API_BASE_PATH}/leads/pipelines",
        data_selector="_embedded.pipelines",
        primary_key=["id"],
        paginated=False,
    ),
    "Users": KommoEndpoint(
        path=f"{API_BASE_PATH}/users",
        data_selector="_embedded.users",
        primary_key=["id"],
        params={"with": "role,group"},
    ),
    "Catalogs": KommoEndpoint(
        path=f"{API_BASE_PATH}/catalogs",
        data_selector="_embedded.catalogs",
        primary_key=["id"],
    ),
    "LeadCustomFields": KommoEndpoint(
        path=f"{API_BASE_PATH}/leads/custom_fields",
        data_selector="_embedded.custom_fields",
        primary_key=["id"],
    ),
    "ContactCustomFields": KommoEndpoint(
        path=f"{API_BASE_PATH}/contacts/custom_fields",
        data_selector="_embedded.custom_fields",
        primary_key=["id"],
    ),
    "CompanyCustomFields": KommoEndpoint(
        path=f"{API_BASE_PATH}/companies/custom_fields",
        data_selector="_embedded.custom_fields",
        primary_key=["id"],
    ),
    "LeadTags": KommoEndpoint(
        path=f"{API_BASE_PATH}/leads/tags",
        data_selector="_embedded.tags",
        primary_key=["id"],
    ),
    "ContactTags": KommoEndpoint(
        path=f"{API_BASE_PATH}/contacts/tags",
        data_selector="_embedded.tags",
        primary_key=["id"],
    ),
    "CompanyTags": KommoEndpoint(
        path=f"{API_BASE_PATH}/companies/tags",
        data_selector="_embedded.tags",
        primary_key=["id"],
    ),
}

ENDPOINTS = tuple(ENDPOINT_CONFIG.keys())


def _updated_at_field() -> list[IncrementalField]:
    return [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.Integer,
        }
    ]


INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: _updated_at_field() for name, endpoint in ENDPOINT_CONFIG.items() if endpoint.incremental_param is not None
}
