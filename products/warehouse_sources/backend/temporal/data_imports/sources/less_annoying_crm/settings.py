from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# Less Annoying CRM's v2 API is RPC-shaped: every call is a POST to a single endpoint carrying a
# `Function` name and a `Parameters` object. Each endpoint below maps a warehouse table to the LACRM
# function that returns it, plus how to page through and where the records live in the response.


@dataclass
class LessAnnoyingCRMEndpointConfig:
    name: str
    # LACRM Function name sent in the request body (e.g. "GetContacts").
    function: str
    # jsonpath selecting the record collection in the response, or None when the body is itself the
    # array of records (GetUsers / GetTeams return a bare JSON array). List endpoints nest under
    # "Results"; GetTasks nests its results as an object keyed by id, so it uses "Results.*" to expand
    # to the dict's values (one row per task) — a bare "Results" would yield the whole object as one row.
    data_selector: Optional[str]
    primary_keys: list[str]
    # Whether the function pages via Page / MaxNumberOfResults. Small reference tables (users, teams)
    # return everything in one call and reject / ignore pagination params, so they're single-shot.
    paginated: bool = True
    # Stable creation-time field used for datetime partitioning. Never a mutable field like LastUpdate.
    partition_key: Optional[str] = None
    # (start_param, end_param) for functions that REQUIRE a date window (GetTasks). We send a very
    # wide window so a full refresh still returns every row. These filter on the record's domain date
    # (due/event date), NOT on a modification timestamp — see the incremental note below.
    date_window_params: Optional[tuple[str, str]] = None
    # Sort params to request a stable ascending order while paging. Which are accepted varies per
    # function: only GetContacts takes a `SortBy` field (e.g. DateCreated); GetTasks and GetNotes
    # expose `SortDirection` alone (their sort column is fixed by the API), so we set direction
    # without a `SortBy` there. Sending an unsupported `SortBy` to those functions would be rejected.
    sort_by: Optional[str] = None
    sort_direction: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True


# A date window wide enough to cover every plausible task/event date on a full refresh. GetTasks
# requires StartDate/EndDate, so we always send this range rather than a modification-time cutoff.
WIDE_WINDOW_START = "1970-01-01T00:00:00Z"
WIDE_WINDOW_END = "2200-01-01T00:00:00Z"


LESS_ANNOYING_CRM_ENDPOINTS: dict[str, LessAnnoyingCRMEndpointConfig] = {
    "users": LessAnnoyingCRMEndpointConfig(
        name="users",
        function="GetUsers",
        data_selector=None,
        primary_keys=["UserId"],
        paginated=False,
    ),
    "teams": LessAnnoyingCRMEndpointConfig(
        name="teams",
        function="GetTeams",
        data_selector=None,
        primary_keys=["TeamId"],
        paginated=False,
    ),
    "contacts": LessAnnoyingCRMEndpointConfig(
        name="contacts",
        function="GetContacts",
        data_selector="Results",
        primary_keys=["ContactId"],
        partition_key="DateCreated",
        sort_by="DateCreated",
        sort_direction="Ascending",
    ),
    "tasks": LessAnnoyingCRMEndpointConfig(
        name="tasks",
        function="GetTasks",
        data_selector="Results.*",
        primary_keys=["TaskId"],
        partition_key="DateCreated",
        date_window_params=("StartDate", "EndDate"),
        sort_direction="Ascending",
    ),
    "notes": LessAnnoyingCRMEndpointConfig(
        name="notes",
        function="GetNotes",
        data_selector="Results",
        primary_keys=["NoteId"],
        partition_key="DateCreated",
        sort_direction="Ascending",
    ),
    "events": LessAnnoyingCRMEndpointConfig(
        name="events",
        function="GetEvents",
        data_selector="Results",
        primary_keys=["EventId"],
        partition_key="DateCreated",
    ),
}

ENDPOINTS = tuple(LESS_ANNOYING_CRM_ENDPOINTS.keys())

# Every endpoint ships full refresh. LACRM exposes no server-side "modified since" filter: contacts
# can only be sorted by LastUpdate (not filtered), and the date windows on GetTasks/GetEvents/GetNotes
# filter on the record's domain date (due/event/entry date), not on a modification timestamp — so they
# can't drive a correct incremental cursor. Enabling incremental would need live verification against a
# real account, so we intentionally advertise no incremental fields for now.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in LESS_ANNOYING_CRM_ENDPOINTS}
