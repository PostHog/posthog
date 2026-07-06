from dataclasses import dataclass, field

# Per-account base URL. `{domain}` is the customer's Agile CRM subdomain
# (e.g. `acme` for https://acme.agilecrm.com). HTTPS only.
BASE_URL_TEMPLATE = "https://{domain}.agilecrm.com/dev/api"

# Agile CRM caps list responses and recommends a page size around 200 to avoid timeouts.
DEFAULT_PAGE_SIZE = 200


@dataclass
class AgileCRMEndpointConfig:
    name: str
    # Path appended to the per-account base URL (no leading slash).
    path: str
    # Dotted path to the list inside the response body, or None when the body *is* the list.
    # Agile CRM list endpoints return a bare JSON array, so this is None for all known endpoints.
    data_selector: str | None = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    page_size: int = DEFAULT_PAGE_SIZE
    should_sync_default: bool = True


# Agile CRM exposes a plain REST/JSON API with cursor pagination (page_size + a `cursor`
# returned on the last item of each page). It documents no server-side updated-since/created-after
# filter on any list endpoint, so every table is full refresh only.
AGILECRM_ENDPOINTS: dict[str, AgileCRMEndpointConfig] = {
    # Contacts of type PERSON.
    "contacts": AgileCRMEndpointConfig(name="contacts", path="contacts"),
    # Contacts of type COMPANY (Agile CRM stores companies in the same backing store as contacts
    # but exposes them through a dedicated list endpoint).
    "companies": AgileCRMEndpointConfig(name="companies", path="contacts/companies/list"),
    # Deals / opportunities.
    "deals": AgileCRMEndpointConfig(name="deals", path="opportunity"),
    # Tasks.
    "tasks": AgileCRMEndpointConfig(name="tasks", path="tasks"),
    # Calendar events.
    "events": AgileCRMEndpointConfig(name="events", path="events"),
}

ENDPOINTS = tuple(AGILECRM_ENDPOINTS.keys())
