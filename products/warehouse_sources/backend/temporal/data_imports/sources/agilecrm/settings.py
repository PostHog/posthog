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
    # Tracks and their milestones — the lookup that decodes the `milestone` field on every deal.
    # A small, un-paginated list; the cursor paginator ends after the first (short) page.
    "pipelines": AgileCRMEndpointConfig(name="pipelines", path="milestone/pipelines"),
}

# Help-desk tickets. Listing goes through `tickets/filter`, which requires a saved-filter id; we
# resolve the account's "All Tickets" system filter from `tickets/filters` at sync time. Not part of
# AGILECRM_ENDPOINTS because it needs that extra resolution step rather than the plain list path.
TICKETS_LIST_PATH = "tickets/filter"
TICKETS_FILTERS_PATH = "tickets/filters"
# The system filter that returns every ticket regardless of status.
TICKETS_ALL_FILTER_NAME = "All Tickets"
# Newest-first is the only stable sort the endpoint documents; order is irrelevant for full refresh.
TICKETS_SORT_KEY = "-last_updated_time"
TICKETS_PRIMARY_KEYS = ["id"]


@dataclass(frozen=True)
class AgileCRMFanoutConfig:
    name: str
    # Endpoint name whose rows supply the parent ids to fan out over.
    parent: str
    # List path for the parent resource (unused when `parent` is "tickets", which needs filter resolution).
    parent_path: str
    # Child path with a single `{parent_id}` placeholder, e.g. "contacts/{parent_id}/notes".
    child_path_template: str
    # Column the parent id is written to on each child row.
    parent_id_field: str
    # Composite key: a note/message id is only unique within its parent, so the parent id is part of it.
    primary_keys: list[str]
    page_size: int = DEFAULT_PAGE_SIZE


# Fan-out tables: iterate a parent resource, then read each parent's child list. Agile CRM exposes
# notes and ticket messages only per parent — there is no account-wide list endpoint for them.
AGILECRM_FANOUT_ENDPOINTS: dict[str, AgileCRMFanoutConfig] = {
    # Notes attached to contacts.
    "contact_notes": AgileCRMFanoutConfig(
        name="contact_notes",
        parent="contacts",
        parent_path="contacts",
        child_path_template="contacts/{parent_id}/notes",
        parent_id_field="contact_id",
        primary_keys=["contact_id", "id"],
    ),
    # Notes attached to deals (opportunities).
    "deal_notes": AgileCRMFanoutConfig(
        name="deal_notes",
        parent="deals",
        parent_path="opportunity",
        child_path_template="opportunity/{parent_id}/notes",
        parent_id_field="deal_id",
        primary_keys=["deal_id", "id"],
    ),
    # The message/note thread inside each ticket.
    "ticket_notes": AgileCRMFanoutConfig(
        name="ticket_notes",
        parent="tickets",
        parent_path=TICKETS_LIST_PATH,
        child_path_template="tickets/notes/{parent_id}",
        parent_id_field="ticket_id",
        primary_keys=["ticket_id", "id"],
    ),
}

ENDPOINTS = (*AGILECRM_ENDPOINTS.keys(), "tickets", *AGILECRM_FANOUT_ENDPOINTS.keys())
