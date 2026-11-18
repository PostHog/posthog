from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    incremental_field,
)

TINYEMAIL_BASE_URL = "https://api.tinyemail.com/v1"

# tinyEmail does not document a maximum page size, so these mirror the page sizes the
# vendor's own tooling has verified against the live API. Campaign pages are 0-indexed
# while contact member pages are 1-indexed.
CAMPAIGNS_PAGE_SIZE = 20
CONTACT_MEMBERS_PAGE_SIZE = 100

# The new-subscriber engagement report rejects a from/to range longer than 7 days.
NEW_SUBSCRIBER_ENGAGEMENT_WINDOW_DAYS = 7
NEW_SUBSCRIBER_ENGAGEMENT_HISTORY_DAYS = 90


@dataclass(frozen=False)
class TinyemailEndpointConfig:
    name: str
    path: str
    data_selector: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    page_size: int = CONTACT_MEMBERS_PAGE_SIZE
    paginated: bool = False
    base_page: int = 0
    primary_key: str | list[str] = "id"
    method: Literal["get", "post", "put"] = "get"
    fanout: DependentEndpointConfig | None = None


TINYEMAIL_ENDPOINTS: dict[str, TinyemailEndpointConfig] = {
    "campaigns": TinyemailEndpointConfig(
        name="campaigns",
        # The list path really is singular, with rows wrapped in `campaigns.content`.
        path="/campaign",
        data_selector="campaigns.content",
        paginated=True,
        base_page=0,
        page_size=CAMPAIGNS_PAGE_SIZE,
    ),
    "contacts": TinyemailEndpointConfig(
        name="contacts",
        path="/contacts",
        data_selector="contacts",
    ),
    "contact_members": TinyemailEndpointConfig(
        name="contact_members",
        path="/contacts/{contact_id}/members",
        data_selector="members.content",
        paginated=True,
        base_page=1,
        page_size=CONTACT_MEMBERS_PAGE_SIZE,
        # Members carry no id of their own and an email is only unique within one contact
        # list, so the parent contact id is part of the key to keep it unique table-wide.
        primary_key=["contact_id", "email"],
        fanout=DependentEndpointConfig(
            parent_name="contacts",
            resolve_param="contact_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "contact_id"},
        ),
    ),
    "sender_details": TinyemailEndpointConfig(
        name="sender_details",
        path="/sender-details",
        data_selector="senderDetailses",
    ),
    "suppressions": TinyemailEndpointConfig(
        name="suppressions",
        path="/suppression",
        data_selector="suppressions",
    ),
    "campaign_domain_stats": TinyemailEndpointConfig(
        name="campaign_domain_stats",
        # A POST that takes the campaign id in the JSON body, so it has its own iterator.
        path="/campaign/domain-stats",
        method="post",
        data_selector="content",
        paginated=True,
        base_page=0,
        page_size=CAMPAIGNS_PAGE_SIZE,
        primary_key=["campaign_id", "domainName"],
    ),
    "new_subscriber_engagement": TinyemailEndpointConfig(
        name="new_subscriber_engagement",
        # A POST that takes the audience ids and a date range in the JSON body, so it has its own iterator.
        path="/report/audience/new-subscriber-engagement",
        method="post",
        data_selector="$",
        incremental_fields=[incremental_field("date", IncrementalFieldType.Date)],
        primary_key=["audience_id", "date"],
    ),
    "clean_history": TinyemailEndpointConfig(
        name="clean_history",
        # Reading the history is a PUT. `PUT /audiences/clean-list/{id}` without the `/history`
        # suffix starts a paid list clean, so this path must keep its suffix.
        path="/audiences/clean-list/{audience_id}/history",
        method="put",
        data_selector="histories",
        primary_key=["audience_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="contacts",
            resolve_param="audience_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "audience_id"},
        ),
    ),
}

ENDPOINTS = tuple(TINYEMAIL_ENDPOINTS)

# tinyEmail exposes no server-side updated-after/since filter on any list endpoint. Only the
# engagement report takes a date range, so it is the one incremental table.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TINYEMAIL_ENDPOINTS.items()
}

# Opens and clicks keep arriving after a campaign is sent, so each incremental run reads the
# last full window again.
INCREMENTAL_LOOKBACK_SECONDS = {"new_subscriber_engagement": NEW_SUBSCRIBER_ENGAGEMENT_WINDOW_DAYS * 24 * 60 * 60}
