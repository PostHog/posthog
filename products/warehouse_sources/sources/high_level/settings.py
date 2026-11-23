import dataclasses
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from products.warehouse_sources.sources.sdk import IncrementalField, incremental_field

HIGHLEVEL_BASE_URL = "https://services.leadconnectorhq.com"

# HighLevel sends the API version in the `Version` request header. v3 is the newest supported
# version (released 2026-06-11); the dated versions (2021-04-15, 2021-07-28) are older.
HIGHLEVEL_API_VERSION_V3 = "v3"

# HighLevel indexes contact changes a few seconds after they happen, and its docs tell incremental
# readers to start each sync a little before the previous one ended. The merge dedupes on `id`.
CONTACTS_INCREMENTAL_LOOKBACK_SECONDS = 600

# The submissions endpoints only return the last month when `startAt` is absent, so a full read
# sends an explicit start date from before HighLevel existed.
SUBMISSIONS_EARLIEST_DATE = "2000-01-01"

# GET /calendars/events has no paging and answers only for a time window, so a read walks one
# window at a time, from 2018 (the year HighLevel launched) to a year ahead for booked appointments.
CALENDAR_EVENTS_EARLIEST = datetime(2018, 1, 1, tzinfo=UTC)
CALENDAR_EVENTS_WINDOW = timedelta(days=30)
CALENDAR_EVENTS_LOOKAHEAD = timedelta(days=365)


class Pagination(StrEnum):
    SINGLE = "single"
    OFFSET = "offset"
    PAGE = "page"
    CURSOR = "cursor"
    CONTACTS_SEARCH_AFTER = "contacts_search_after"
    OPPORTUNITIES_START_AFTER = "opportunities_start_after"
    CONVERSATIONS_START_AFTER_DATE = "conversations_start_after_date"
    CALENDAR_EVENT_WINDOWS = "calendar_event_windows"


class LocationParam(StrEnum):
    # `?locationId=<id>`
    QUERY = "query"
    # `?altId=<id>&altType=location`, used by the invoices, payments and products APIs.
    ALT_ID = "alt_id"
    # The path carries `{location_id}`.
    PATH = "path"
    # The route takes no location, because the parent in the path belongs to one.
    NONE = "none"


class IncrementalFilter(StrEnum):
    # A `dateUpdated` range filter in the POST /contacts/search body.
    CONTACTS_DATE_UPDATED_RANGE = "contacts_date_updated_range"
    # `startDate` as an ISO 8601 timestamp.
    START_DATE_TIMESTAMP = "start_date_timestamp"
    # `startAt` as a YYYY-MM-DD day.
    START_AT_DAY = "start_at_day"


@dataclasses.dataclass(frozen=True)
class FanOut:
    """A child route that runs once for each row of its parent, with `{parent_id}` in its path."""

    parent: "HighLevelEndpointConfig"
    parent_field: str = "id"
    # The child row field that names the parent. It is filled from the parent when the API leaves it out.
    child_field: str | None = None


@dataclasses.dataclass(frozen=True)
class HighLevelEndpointConfig:
    name: str
    path: str
    data_selector: str
    pagination: Pagination
    scope: str
    primary_keys: tuple[str, ...] = ("id",)
    method: str = "get"
    page_size: int = 100
    location_param: LocationParam = LocationParam.QUERY
    offset_param: str = "offset"
    total_path: str | None = None
    extra_params: dict[str, str] = dataclasses.field(default_factory=dict)
    partition_key: str | None = None
    incremental_fields: list[IncrementalField] = dataclasses.field(default_factory=list)
    incremental_filter: IncrementalFilter | None = None
    fan_out: FanOut | None = None


def _messages_endpoint(name: str, extra_params: dict[str, str]) -> HighLevelEndpointConfig:
    return HighLevelEndpointConfig(
        name=name,
        path="/conversations/messages/export",
        data_selector="messages",
        pagination=Pagination.CURSOR,
        scope="conversations/message.readonly",
        page_size=500,
        # Ascending creation order keeps the cursor walk stable while new messages arrive.
        extra_params={"sortBy": "createdAt", "sortOrder": "asc", **extra_params},
        partition_key="dateAdded",
        # Only the creation time can be filtered. A delivery status that changes after the
        # message was synced is not read again by an incremental sync.
        incremental_fields=[incremental_field("dateAdded")],
        incremental_filter=IncrementalFilter.START_DATE_TIMESTAMP,
    )


def _submissions_endpoint(name: str, path: str, scope: str) -> HighLevelEndpointConfig:
    return HighLevelEndpointConfig(
        name=name,
        path=path,
        data_selector="submissions",
        pagination=Pagination.PAGE,
        scope=scope,
        partition_key="createdAt",
        # A submission does not change after it is created.
        incremental_fields=[incremental_field("createdAt")],
        incremental_filter=IncrementalFilter.START_AT_DAY,
    )


def _payments_endpoint(name: str, path: str, scope: str) -> HighLevelEndpointConfig:
    return HighLevelEndpointConfig(
        name=name,
        path=path,
        data_selector="data",
        pagination=Pagination.OFFSET,
        scope=scope,
        primary_keys=("_id",),
        location_param=LocationParam.ALT_ID,
        total_path="totalCount",
        partition_key="createdAt",
    )


CONTACTS = HighLevelEndpointConfig(
    name="contacts",
    path="/contacts/search",
    method="post",
    data_selector="contacts",
    pagination=Pagination.CONTACTS_SEARCH_AFTER,
    scope="contacts.readonly",
    page_size=500,
    location_param=LocationParam.QUERY,
    partition_key="dateAdded",
    incremental_fields=[incremental_field("dateUpdated")],
    incremental_filter=IncrementalFilter.CONTACTS_DATE_UPDATED_RANGE,
)

CALENDARS = HighLevelEndpointConfig(
    name="calendars",
    path="/calendars/",
    data_selector="calendars",
    pagination=Pagination.SINGLE,
    scope="calendars.readonly",
)

# The sub-account itself. It is not a table: the users route needs the agency (company) ID, and
# only the location answers it.
LOCATION = HighLevelEndpointConfig(
    name="location",
    path="/locations/{location_id}",
    data_selector="location",
    pagination=Pagination.SINGLE,
    scope="locations.readonly",
    location_param=LocationParam.PATH,
)


HIGHLEVEL_ENDPOINTS: dict[str, HighLevelEndpointConfig] = {
    endpoint.name: endpoint
    for endpoint in (
        CONTACTS,
        HighLevelEndpointConfig(
            name="opportunities",
            path="/opportunities/search",
            data_selector="opportunities",
            pagination=Pagination.OPPORTUNITIES_START_AFTER,
            scope="opportunities.readonly",
            partition_key="createdAt",
        ),
        HighLevelEndpointConfig(
            name="pipelines",
            path="/opportunities/pipelines",
            data_selector="pipelines",
            pagination=Pagination.SINGLE,
            scope="opportunities.readonly",
        ),
        CALENDARS,
        HighLevelEndpointConfig(
            name="calendar_groups",
            path="/calendars/groups",
            data_selector="groups",
            pagination=Pagination.SINGLE,
            scope="calendars/groups.readonly",
        ),
        HighLevelEndpointConfig(
            name="conversations",
            path="/conversations/search",
            data_selector="conversations",
            pagination=Pagination.CONVERSATIONS_START_AFTER_DATE,
            scope="conversations.readonly",
            extra_params={"sortBy": "last_message_date", "sort": "desc"},
        ),
        # Without a channel the export returns every message type except email, and email needs
        # `channel=Email`, so email messages are a table of their own.
        _messages_endpoint("messages", {}),
        _messages_endpoint("email_messages", {"channel": "Email"}),
        HighLevelEndpointConfig(
            name="custom_fields",
            path="/locations/{location_id}/customFields",
            data_selector="customFields",
            pagination=Pagination.SINGLE,
            scope="locations/customFields.readonly",
            location_param=LocationParam.PATH,
        ),
        HighLevelEndpointConfig(
            name="tags",
            path="/locations/{location_id}/tags",
            data_selector="tags",
            pagination=Pagination.SINGLE,
            scope="locations/tags.readonly",
            location_param=LocationParam.PATH,
        ),
        HighLevelEndpointConfig(
            name="forms",
            path="/forms/",
            data_selector="forms",
            pagination=Pagination.OFFSET,
            scope="forms.readonly",
            page_size=50,
            offset_param="skip",
            total_path="total",
        ),
        _submissions_endpoint("form_submissions", "/forms/submissions", "forms.readonly"),
        HighLevelEndpointConfig(
            name="surveys",
            path="/surveys/",
            data_selector="surveys",
            pagination=Pagination.OFFSET,
            scope="surveys.readonly",
            page_size=50,
            offset_param="skip",
            total_path="total",
        ),
        _submissions_endpoint("survey_submissions", "/surveys/submissions", "surveys.readonly"),
        HighLevelEndpointConfig(
            name="invoices",
            path="/invoices/",
            data_selector="invoices",
            pagination=Pagination.OFFSET,
            scope="invoices.readonly",
            primary_keys=("_id",),
            location_param=LocationParam.ALT_ID,
            total_path="total",
            partition_key="createdAt",
        ),
        _payments_endpoint("transactions", "/payments/transactions", "payments/transactions.readonly"),
        _payments_endpoint("orders", "/payments/orders", "payments/orders.readonly"),
        _payments_endpoint("subscriptions", "/payments/subscriptions", "payments/subscriptions.readonly"),
        HighLevelEndpointConfig(
            name="products",
            path="/products/",
            data_selector="products",
            pagination=Pagination.OFFSET,
            scope="products.readonly",
            primary_keys=("_id",),
            total_path="total[0].total",
            partition_key="createdAt",
        ),
        HighLevelEndpointConfig(
            name="workflows",
            path="/workflows/",
            data_selector="workflows",
            pagination=Pagination.SINGLE,
            scope="workflows.readonly",
        ),
        HighLevelEndpointConfig(
            name="campaigns",
            path="/campaigns/",
            data_selector="campaigns",
            pagination=Pagination.SINGLE,
            scope="campaigns.readonly",
        ),
        HighLevelEndpointConfig(
            name="lost_reasons",
            path="/opportunities/lost-reason",
            data_selector="lostReasons",
            pagination=Pagination.OFFSET,
            scope="opportunities.readonly",
            offset_param="skip",
            total_path="total",
            partition_key="createdAt",
        ),
        HighLevelEndpointConfig(
            name="users",
            # v3 has no GET /users/. The search route needs the agency (company) ID as well.
            path="/users/search?companyId={parent_id}",
            data_selector="users",
            pagination=Pagination.OFFSET,
            scope="users.readonly",
            # 25 is the documented default and the maximum is not documented. The offset paginator
            # steps by the page size, so a larger size that HighLevel capped would skip users.
            page_size=25,
            offset_param="skip",
            total_path="count",
            fan_out=FanOut(parent=LOCATION, parent_field="companyId"),
        ),
        HighLevelEndpointConfig(
            name="calendar_events",
            path="/calendars/events?calendarId={parent_id}",
            data_selector="events",
            pagination=Pagination.CALENDAR_EVENT_WINDOWS,
            scope="calendars/events.readonly",
            primary_keys=("calendarId", "id"),
            partition_key="dateAdded",
            fan_out=FanOut(parent=CALENDARS, child_field="calendarId"),
        ),
        HighLevelEndpointConfig(
            name="contact_notes",
            path="/contacts/{parent_id}/notes",
            data_selector="notes",
            pagination=Pagination.SINGLE,
            scope="contacts.readonly",
            primary_keys=("contactId", "id"),
            location_param=LocationParam.NONE,
            partition_key="dateAdded",
            fan_out=FanOut(parent=CONTACTS, child_field="contactId"),
        ),
    )
}

ENDPOINTS = tuple(HIGHLEVEL_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HIGHLEVEL_ENDPOINTS.items() if config.incremental_fields
}

REQUIRED_SCOPES = tuple(
    sorted(
        {config.scope for config in HIGHLEVEL_ENDPOINTS.values()}
        | {config.fan_out.parent.scope for config in HIGHLEVEL_ENDPOINTS.values() if config.fan_out}
    )
)
