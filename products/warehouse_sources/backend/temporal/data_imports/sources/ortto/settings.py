from dataclasses import dataclass
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField

OrttoPaginationMode = Literal["cursor", "offset", "none"]

# Region-specific API hosts — an API key only works against its instance's region.
ORTTO_REGION_HOSTS: dict[str, str] = {
    "global": "https://api.ap3api.com",
    "au": "https://api.au.ap3api.com",
    "eu": "https://api.eu.ap3api.com",
}

# Built-in person field IDs documented for /v1/person/get. Custom fields
# (str:cm:*, int:cm:*, ...) are discovered at runtime and appended.
PERSON_BUILTIN_FIELDS: list[str] = [
    "str::first",
    "str::last",
    "str::email",
    "str::postal",
    "str::ei",
    "phn::phone",
    "geo::city",
    "geo::region",
    "geo::country",
    "bol::gdpr",
    "bol::p",
    "bol::sp",
    "dtz::b",
    "u4s::t",
    "idt::o",
]

# Built-in account (organization) field IDs documented for /v1/accounts/get.
ACCOUNT_BUILTIN_FIELDS: list[str] = [
    "str:o:name",
    "str:o:website",
    "str:o:industry",
    "int:o:employees",
]


@dataclass
class OrttoEndpointConfig:
    path: str
    # Key holding the row list in the response body; None when the body is the list.
    data_key: str | None
    pagination: OrttoPaginationMode
    page_size: int = 500
    # Built-in field IDs to request; merged with runtime-discovered custom
    # fields from this custom-field listing path.
    builtin_fields: list[str] | None = None
    custom_fields_path: str | None = None


# Every Ortto retrieval endpoint is a POST with pagination in the JSON body.
# There is no server-side updated-since filter (Fivetran's connector re-imports
# every table per sync for the same reason), so all streams are full refresh;
# resume state persists the pagination position within a single sync.
ORTTO_ENDPOINTS: dict[str, OrttoEndpointConfig] = {
    "people": OrttoEndpointConfig(
        path="/v1/person/get",
        data_key="contacts",
        pagination="cursor",
        builtin_fields=PERSON_BUILTIN_FIELDS,
        custom_fields_path="/v1/person/custom-field/get",
    ),
    "accounts": OrttoEndpointConfig(
        path="/v1/accounts/get",
        data_key="accounts",
        pagination="cursor",
        builtin_fields=ACCOUNT_BUILTIN_FIELDS,
        custom_fields_path="/v1/accounts/custom-field/get",
    ),
    "audiences": OrttoEndpointConfig(
        path="/v1/audiences/get",
        data_key=None,
        pagination="offset",
        # Documented max page size for audiences.
        page_size=40,
    ),
    "tags": OrttoEndpointConfig(
        path="/v1/tags/get",
        data_key=None,
        pagination="none",
    ),
    "person_custom_fields": OrttoEndpointConfig(
        path="/v1/person/custom-field/get",
        data_key="fields",
        pagination="none",
    ),
    "account_custom_fields": OrttoEndpointConfig(
        path="/v1/accounts/custom-field/get",
        data_key="fields",
        pagination="none",
    ),
}

ENDPOINTS = tuple(ORTTO_ENDPOINTS.keys())

# No endpoint exposes a server-side updated-since filter, so nothing is honestly incremental.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
