from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

TINYEMAIL_BASE_URL = "https://api.tinyemail.com/v1"

# tinyEmail does not document a maximum page size, so these mirror the page sizes the
# vendor's own tooling has verified against the live API. Campaign pages are 0-indexed
# while contact member pages are 1-indexed.
CAMPAIGNS_PAGE_SIZE = 20
CONTACT_MEMBERS_PAGE_SIZE = 100


@dataclass
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
}

ENDPOINTS = tuple(TINYEMAIL_ENDPOINTS)

# tinyEmail exposes no server-side updated-after/since filter on any endpoint, so every
# table is full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in TINYEMAIL_ENDPOINTS}
