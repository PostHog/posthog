from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How a collection endpoint pages:
# - "offset": Mailchimp's standard `count`/`offset` pagination, looped until `total_items`.
# - "count_only": the endpoint accepts `count` but no `offset`, so it is a single capped request.
# - "none": the endpoint takes no pagination params and returns the whole collection at once.
MailchimpPagination = Literal["offset", "count_only", "none"]

MAX_PAGE_SIZE = 1000  # Mailchimp caps `count` at 1000 across the API


@dataclass
class MailchimpParentConfig:
    """One hop of a fan-out chain.

    ``path`` may itself contain ``{placeholder}`` names resolved by earlier hops, so chains
    deeper than one level (audience -> segment -> member) compose without bespoke code.
    ``inject_as`` is both the placeholder name in the child path and the column written onto
    every child row, which is what makes the parent id available for the primary key.
    """

    path: str
    data_selector: str
    id_field: str = "id"
    inject_as: str = "id"


@dataclass
class MailchimpEndpointConfig:
    name: str
    path: str
    data_selector: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    partition_key: Optional[str] = None
    page_size: int = MAX_PAGE_SIZE
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    parents: tuple[MailchimpParentConfig, ...] = ()
    pagination: MailchimpPagination = "offset"
    single_object: bool = False
    """Endpoint returns one object rather than a collection, so it yields a single row per parent."""
    incremental_params: dict[str, str] = field(default_factory=dict)
    """Maps an incremental field name to the Mailchimp query param that filters on it server-side."""
    chunk_size: Optional[int] = None
    chunk_size_bytes: Optional[int] = None


_LISTS_PARENT = MailchimpParentConfig(path="/lists", data_selector="lists", inject_as="list_id")
_CAMPAIGNS_PARENT = MailchimpParentConfig(path="/campaigns", data_selector="campaigns", inject_as="campaign_id")
# Reports only exist for campaigns that have actually been sent, so fanning report sub-resources
# out over /reports avoids a 404 per unsent draft.
_REPORTS_PARENT = MailchimpParentConfig(path="/reports", data_selector="reports", inject_as="campaign_id")
_AUTOMATIONS_PARENT = MailchimpParentConfig(path="/automations", data_selector="automations", inject_as="workflow_id")
_STORES_PARENT = MailchimpParentConfig(path="/ecommerce/stores", data_selector="stores", inject_as="store_id")


MAILCHIMP_ENDPOINTS: dict[str, MailchimpEndpointConfig] = {
    "lists": MailchimpEndpointConfig(
        name="lists",
        path="/lists",
        data_selector="lists",
        incremental_fields=[],
        partition_key="date_created",
    ),
    "campaigns": MailchimpEndpointConfig(
        name="campaigns",
        path="/campaigns",
        data_selector="campaigns",
        incremental_fields=[],
        partition_key="create_time",
        incremental_params={"create_time": "since_create_time", "send_time": "since_send_time"},
    ),
    "reports": MailchimpEndpointConfig(
        name="reports",
        path="/reports",
        data_selector="reports",
        incremental_fields=[],
        partition_key="send_time",
        incremental_params={"send_time": "since_send_time"},
    ),
    "contacts": MailchimpEndpointConfig(
        name="contacts",
        path="/lists/{list_id}/members",  # Special: iterates over all lists
        data_selector="members",
        partition_key=None,  # No stable timestamp field available
        default_incremental_field="last_changed",
        primary_keys=["list_id", "id"],
        incremental_fields=[
            {
                "label": "last_changed",
                "type": IncrementalFieldType.DateTime,
                "field": "last_changed",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # --- Account-level collections ---
    "automations": MailchimpEndpointConfig(
        name="automations",
        path="/automations",
        data_selector="automations",
        partition_key="create_time",
        default_incremental_field="create_time",
        incremental_params={"create_time": "since_create_time", "start_time": "since_start_time"},
        incremental_fields=[
            {
                "label": "create_time",
                "type": IncrementalFieldType.DateTime,
                "field": "create_time",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "start_time",
                "type": IncrementalFieldType.DateTime,
                "field": "start_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "templates": MailchimpEndpointConfig(
        name="templates",
        path="/templates",
        data_selector="templates",
        partition_key="date_created",
        default_incremental_field="date_created",
        incremental_params={"date_created": "since_date_created"},
        incremental_fields=[
            {
                "label": "date_created",
                "type": IncrementalFieldType.DateTime,
                "field": "date_created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "sms_campaigns": MailchimpEndpointConfig(
        name="sms_campaigns",
        path="/sms-campaigns",
        data_selector="sms_campaigns",
        incremental_fields=[],
        partition_key="create_time",
    ),
    "conversations": MailchimpEndpointConfig(
        name="conversations",
        path="/conversations",
        data_selector="conversations",
        incremental_fields=[],
    ),
    "campaign_folders": MailchimpEndpointConfig(
        name="campaign_folders",
        path="/campaign-folders",
        data_selector="folders",
        incremental_fields=[],
    ),
    "ecommerce_stores": MailchimpEndpointConfig(
        name="ecommerce_stores",
        path="/ecommerce/stores",
        data_selector="stores",
        incremental_fields=[],
        partition_key="created_at",
    ),
    "ecommerce_orders": MailchimpEndpointConfig(
        name="ecommerce_orders",
        path="/ecommerce/orders",
        data_selector="orders",
        incremental_fields=[],
        # Order ids come from the connected store, so they are only unique within a store.
        primary_keys=["store_id", "id"],
        partition_key="processed_at_foreign",
    ),
    "landing_pages": MailchimpEndpointConfig(
        name="landing_pages",
        path="/landing-pages",
        data_selector="landing_pages",
        incremental_fields=[],
        pagination="count_only",  # the endpoint accepts `count` but has no `offset`
        partition_key="created_at",
    ),
    "verified_domains": MailchimpEndpointConfig(
        name="verified_domains",
        path="/verified-domains",
        data_selector="domains",
        incremental_fields=[],
        pagination="none",
        primary_keys=["domain"],
    ),
    # --- Audience (list) fan-out ---
    "list_segments": MailchimpEndpointConfig(
        name="list_segments",
        path="/lists/{list_id}/segments",
        data_selector="segments",
        parents=(_LISTS_PARENT,),
        primary_keys=["list_id", "id"],
        partition_key="created_at",
        default_incremental_field="updated_at",
        incremental_params={"created_at": "since_created_at", "updated_at": "since_updated_at"},
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "list_segment_members": MailchimpEndpointConfig(
        name="list_segment_members",
        path="/lists/{list_id}/segments/{segment_id}/members",
        data_selector="members",
        parents=(
            _LISTS_PARENT,
            MailchimpParentConfig(path="/lists/{list_id}/segments", data_selector="segments", inject_as="segment_id"),
        ),
        incremental_fields=[],
        primary_keys=["list_id", "segment_id", "id"],
    ),
    "list_merge_fields": MailchimpEndpointConfig(
        name="list_merge_fields",
        path="/lists/{list_id}/merge-fields",
        data_selector="merge_fields",
        parents=(_LISTS_PARENT,),
        incremental_fields=[],
        primary_keys=["list_id", "merge_id"],
    ),
    "list_interest_categories": MailchimpEndpointConfig(
        name="list_interest_categories",
        path="/lists/{list_id}/interest-categories",
        data_selector="categories",
        parents=(_LISTS_PARENT,),
        incremental_fields=[],
        primary_keys=["list_id", "id"],
    ),
    "list_growth_history": MailchimpEndpointConfig(
        name="list_growth_history",
        path="/lists/{list_id}/growth-history",
        data_selector="history",
        parents=(_LISTS_PARENT,),
        incremental_fields=[],
        primary_keys=["list_id", "month"],
    ),
    "list_activity": MailchimpEndpointConfig(
        name="list_activity",
        path="/lists/{list_id}/activity",
        data_selector="activity",
        parents=(_LISTS_PARENT,),
        incremental_fields=[],
        primary_keys=["list_id", "day"],
    ),
    # --- Campaign fan-out ---
    "campaign_content": MailchimpEndpointConfig(
        name="campaign_content",
        path="/campaigns/{campaign_id}/content",
        data_selector="",  # single object response
        parents=(_CAMPAIGNS_PARENT,),
        incremental_fields=[],
        primary_keys=["campaign_id"],
        pagination="none",
        single_object=True,
        # Rendered HTML makes these rows far larger than a typical API row, so batch fewer of them.
        chunk_size=200,
        chunk_size_bytes=50 * 1024 * 1024,
    ),
    "campaign_feedback": MailchimpEndpointConfig(
        name="campaign_feedback",
        path="/campaigns/{campaign_id}/feedback",
        data_selector="feedback",
        parents=(_CAMPAIGNS_PARENT,),
        incremental_fields=[],
        primary_keys=["campaign_id", "feedback_id"],
        pagination="none",
        partition_key="created_at",
    ),
    # --- Report fan-out (per-recipient engagement) ---
    "report_email_activity": MailchimpEndpointConfig(
        name="report_email_activity",
        path="/reports/{campaign_id}/email-activity",
        data_selector="emails",
        parents=(_REPORTS_PARENT,),
        incremental_fields=[],
        primary_keys=["campaign_id", "email_id"],
    ),
    "report_open_details": MailchimpEndpointConfig(
        name="report_open_details",
        path="/reports/{campaign_id}/open-details",
        data_selector="members",
        parents=(_REPORTS_PARENT,),
        incremental_fields=[],
        primary_keys=["campaign_id", "email_id"],
    ),
    "report_click_details": MailchimpEndpointConfig(
        name="report_click_details",
        path="/reports/{campaign_id}/click-details",
        data_selector="urls_clicked",
        parents=(_REPORTS_PARENT,),
        incremental_fields=[],
        primary_keys=["campaign_id", "id"],
    ),
    "report_sent_to": MailchimpEndpointConfig(
        name="report_sent_to",
        path="/reports/{campaign_id}/sent-to",
        data_selector="sent_to",
        parents=(_REPORTS_PARENT,),
        incremental_fields=[],
        primary_keys=["campaign_id", "email_id"],
    ),
    "report_unsubscribed": MailchimpEndpointConfig(
        name="report_unsubscribed",
        path="/reports/{campaign_id}/unsubscribed",
        data_selector="unsubscribes",
        parents=(_REPORTS_PARENT,),
        incremental_fields=[],
        primary_keys=["campaign_id", "email_id"],
        partition_key="timestamp",
    ),
    "report_abuse_reports": MailchimpEndpointConfig(
        name="report_abuse_reports",
        path="/reports/{campaign_id}/abuse-reports",
        data_selector="abuse_reports",
        parents=(_REPORTS_PARENT,),
        incremental_fields=[],
        primary_keys=["campaign_id", "id"],
        pagination="none",
        partition_key="date",
    ),
    "report_domain_performance": MailchimpEndpointConfig(
        name="report_domain_performance",
        path="/reports/{campaign_id}/domain-performance",
        data_selector="domains",
        parents=(_REPORTS_PARENT,),
        incremental_fields=[],
        primary_keys=["campaign_id", "domain"],
        pagination="none",
    ),
    "report_locations": MailchimpEndpointConfig(
        name="report_locations",
        path="/reports/{campaign_id}/locations",
        data_selector="locations",
        parents=(_REPORTS_PARENT,),
        incremental_fields=[],
        primary_keys=["campaign_id", "country_code", "region"],
    ),
    "report_ecommerce_product_activity": MailchimpEndpointConfig(
        name="report_ecommerce_product_activity",
        path="/reports/{campaign_id}/ecommerce-product-activity",
        data_selector="products",
        parents=(_REPORTS_PARENT,),
        incremental_fields=[],
        primary_keys=["campaign_id", "title", "sku"],
    ),
    # --- Automation fan-out ---
    "automation_emails": MailchimpEndpointConfig(
        name="automation_emails",
        path="/automations/{workflow_id}/emails",
        data_selector="emails",
        parents=(_AUTOMATIONS_PARENT,),
        incremental_fields=[],
        primary_keys=["workflow_id", "id"],
        pagination="none",
        partition_key="create_time",
    ),
    # --- Ecommerce store fan-out ---
    "ecommerce_products": MailchimpEndpointConfig(
        name="ecommerce_products",
        path="/ecommerce/stores/{store_id}/products",
        data_selector="products",
        parents=(_STORES_PARENT,),
        incremental_fields=[],
        primary_keys=["store_id", "id"],
    ),
}

ENDPOINTS = tuple(MAILCHIMP_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MAILCHIMP_ENDPOINTS.items()
}
