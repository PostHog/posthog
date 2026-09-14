"""Hubspot source settings and constants"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

STARTDATE = datetime(year=2000, month=1, day=1)

# Vendor API version labels. HubSpot moved to date-based versioning ("YYYY-MM"); the legacy
# "v3" pin keeps the historical /crm/v3/ (objects, properties) + /crm/v4/ (association
# batch-read) URL split. Under a date version the version segment moves to *after* the API
# resource name, so /crm/v3/objects/... becomes /crm/objects/2026-03/... and
# /crm/v4/associations/... becomes /crm/associations/2026-03/... .
HUBSPOT_API_VERSION_V3 = "v3"
HUBSPOT_API_VERSION_2026_03 = "2026-03"

# Matches the leading "/crm/<v3|v4>/<resource>" of a CRM path, capturing the resource name
# (objects, properties, associations, pipelines, owners) so the version can be re-inserted after
# it. The trailing separator is optional so a resource-only path like "/crm/v3/owners" rewrites too.
_CRM_VERSION_SEGMENT = re.compile(r"^/crm/v[34]/([^/]+)(/|$)")


def apply_crm_api_version(path: str, api_version: str) -> str:
    """Rewrite a HubSpot CRM path to the pinned vendor API version. The legacy "v3" pin is
    returned unchanged so existing syncs are byte-for-byte unaffected. For a date version the
    version segment moves behind the resource name, e.g. /crm/v3/objects/contacts ->
    /crm/objects/2026-03/contacts and /crm/v4/associations/a/b/batch/read ->
    /crm/associations/2026-03/a/b/batch/read."""
    if api_version == HUBSPOT_API_VERSION_V3:
        return path
    return _CRM_VERSION_SEGMENT.sub(rf"/crm/\1/{api_version}\2", path)


# Reading leads requires Sales Hub Professional or above, so `OauthIntegration.oauth_config_for_kind`
# asks HubSpot for this scope as an optional one and a connection can be authorized without it.
LEADS_SCOPE = "crm.objects.leads.read"

CONTACT = "contact"
COMPANY = "company"
DEAL = "deal"
TICKET = "ticket"
QUOTE = "quote"
EMAILS = "emails"
MEETINGS = "meetings"
LEAD = "lead"

CRM_CONTACTS_ENDPOINT = "/crm/v3/objects/contacts?associations=deals,tickets,quotes"
CRM_COMPANIES_ENDPOINT = "/crm/v3/objects/companies?associations=contacts,deals,tickets,quotes"
CRM_DEALS_ENDPOINT = "/crm/v3/objects/deals"
CRM_TICKETS_ENDPOINT = "/crm/v3/objects/tickets"
CRM_QUOTES_ENDPOINT = "/crm/v3/objects/quotes"
CRM_EMAILS_ENDPOINT = "/crm/v3/objects/emails"
CRM_MEETINGS_ENDPOINT = "/crm/v3/objects/meetings"


CRM_OBJECT_ENDPOINTS = {
    CONTACT: CRM_CONTACTS_ENDPOINT,
    COMPANY: CRM_COMPANIES_ENDPOINT,
    DEAL: CRM_DEALS_ENDPOINT,
    TICKET: CRM_TICKETS_ENDPOINT,
    QUOTE: CRM_QUOTES_ENDPOINT,
    EMAILS: CRM_EMAILS_ENDPOINT,
    MEETINGS: CRM_MEETINGS_ENDPOINT,
}

WEB_ANALYTICS_EVENTS_ENDPOINT = "/events/v3/events?objectType={objectType}&objectId={objectId}&occurredAfter={occurredAfter}&occurredBefore={occurredBefore}&sort=-occurredAt"

OBJECT_TYPE_SINGULAR = {
    "companies": COMPANY,
    "contacts": CONTACT,
    "deals": DEAL,
    "tickets": TICKET,
    "quotes": QUOTE,
    "emails": EMAILS,
    "meetings": MEETINGS,
    "leads": LEAD,
}

OBJECT_TYPE_PLURAL = {v: k for k, v in OBJECT_TYPE_SINGULAR.items()}


ENDPOINTS = (
    OBJECT_TYPE_PLURAL[CONTACT],
    OBJECT_TYPE_PLURAL[DEAL],
    OBJECT_TYPE_PLURAL[COMPANY],
    OBJECT_TYPE_PLURAL[TICKET],
    OBJECT_TYPE_PLURAL[QUOTE],
    OBJECT_TYPE_PLURAL[EMAILS],
    OBJECT_TYPE_PLURAL[MEETINGS],
    OBJECT_TYPE_PLURAL[LEAD],
    "calls",
    "notes",
    "tasks",
    "communications",
    "feedback_submissions",
    "line_items",
    "products",
    "invoices",
    "orders",
    "subscriptions",
    "commerce_payments",
    # Lookup tables (see HUBSPOT_METADATA_ENDPOINTS) — not CRM objects.
    "pipelines",
    "pipeline_stages",
    "properties",
    "owners",
)

# CRM search API constants — shared between windowing and pagination logic
SEARCH_PAGE_SIZE = 200
SEARCH_RESULT_CAP = 10_000  # HubSpot returns at most 10k total results per search query
SEARCH_WINDOW_DAYS = 30
ASSOCIATIONS_BATCH_SIZE = 1000  # HubSpot v4 batch-read limit

DEFAULT_DEAL_PROPS = [
    "amount",
    "closedate",
    "createdate",
    "dealname",
    "dealstage",
    "hs_lastmodifieddate",
    "hs_object_id",
    "pipeline",
    "hs_mrr",
]

DEFAULT_COMPANY_PROPS = [
    "createdate",
    "domain",
    "hs_lastmodifieddate",
    "hs_object_id",
    "hs_csm_sentiment",
    "hs_lead_status",
    "name",
]

DEFAULT_CONTACT_PROPS = [
    "createdate",
    "email",
    "firstname",
    "hs_object_id",
    "hs_lead_status",
    "lastmodifieddate",
    "lastname",
    "hs_buying_role",
]

DEFAULT_TICKET_PROPS = [
    "createdate",
    "content",
    "hs_lastmodifieddate",
    "hs_object_id",
    "hs_pipeline",
    "hs_pipeline_stage",
    "hs_ticket_category",
    "hs_ticket_priority",
    "subject",
]

DEFAULT_QUOTE_PROPS = [
    "hs_createdate",
    "hs_expiration_date",
    "hs_lastmodifieddate",
    "hs_object_id",
    "hs_public_url_key",
    "hs_status",
    "hs_title",
]

DEFAULT_EMAIL_PROPS = [
    "hs_timestamp",
    "hs_lastmodifieddate",
    "hs_object_id",
    "hs_email_direction",
    "hs_email_html",
    "hs_email_status",
    "hs_email_subject",
    "hs_email_text",
    "hs_attachment_ids",
    "hs_email_headers",
]

DEFAULT_MEETINGS_PROPS = [
    "hs_timestamp",
    "hs_lastmodifieddate",
    "hs_object_id",
    "hs_meeting_title",
    "hs_meeting_body",
    "hs_internal_meeting_notes",
    "hs_meeting_external_URL",
    "hs_meeting_location",
    "hs_meeting_start_time",
    "hs_meeting_end_time",
    "hs_meeting_outcome",
    "hs_activity_type",
    "hs_attachment_ids",
]

# Lead-specific standard properties are all hs_-prefixed, so custom-property auto-discovery (which
# only pulls non-hs_ props) won't surface them — they must be listed here explicitly.
DEFAULT_LEAD_PROPS = [
    "hs_createdate",
    "hs_lastmodifieddate",
    "hs_lead_label",
    "hs_lead_name",
    "hs_lead_type",
    "hs_object_id",
    "hs_pipeline",
    "hs_pipeline_stage",
]

# Objects added after the original eight request their full property set from
# /crm/v3/properties/{objectType} instead of carrying a hand-written default list (see
# `discover_all_properties` below), so their entry here only seeds the properties HubSpot
# guarantees on every non-contact CRM object: the primary key and the incremental cursor.
# `hs_timestamp` is the activity time on engagement objects, matching emails and meetings above.
BASE_OBJECT_PROPS = ["hs_object_id", "hs_lastmodifieddate"]
BASE_ENGAGEMENT_PROPS = [*BASE_OBJECT_PROPS, "hs_timestamp"]

DEFAULT_PROPS = {
    OBJECT_TYPE_PLURAL[CONTACT]: DEFAULT_CONTACT_PROPS,
    OBJECT_TYPE_PLURAL[COMPANY]: DEFAULT_COMPANY_PROPS,
    OBJECT_TYPE_PLURAL[DEAL]: DEFAULT_DEAL_PROPS,
    OBJECT_TYPE_PLURAL[TICKET]: DEFAULT_TICKET_PROPS,
    OBJECT_TYPE_PLURAL[QUOTE]: DEFAULT_QUOTE_PROPS,
    OBJECT_TYPE_PLURAL[EMAILS]: DEFAULT_EMAIL_PROPS,
    OBJECT_TYPE_PLURAL[MEETINGS]: DEFAULT_MEETINGS_PROPS,
    OBJECT_TYPE_PLURAL[LEAD]: DEFAULT_LEAD_PROPS,
    "calls": BASE_ENGAGEMENT_PROPS,
    "notes": BASE_ENGAGEMENT_PROPS,
    "tasks": BASE_ENGAGEMENT_PROPS,
    "communications": BASE_ENGAGEMENT_PROPS,
    "feedback_submissions": BASE_OBJECT_PROPS,
    "line_items": BASE_OBJECT_PROPS,
    "products": BASE_OBJECT_PROPS,
    "invoices": BASE_OBJECT_PROPS,
    "orders": BASE_OBJECT_PROPS,
    "subscriptions": BASE_OBJECT_PROPS,
    "commerce_payments": BASE_OBJECT_PROPS,
}


def _incremental_field(name: str) -> IncrementalField:
    return IncrementalField(
        label=name,
        type=IncrementalFieldType.DateTime,
        field=name,
        field_type=IncrementalFieldType.DateTime,
    )


@frozen
class HubspotEndpointConfig:
    name: str
    path: str
    associations: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: Optional[str] = None
    # Name of the HubSpot property used both as the search filter and as the incremental cursor
    # (e.g. hs_lastmodifieddate). None means the endpoint does not support incremental sync.
    cursor_filter_property_field: Optional[str] = None
    # Whether this endpoint is selected for sync by default. False keeps a table off unless the
    # user opts in — used for objects that need an OAuth scope existing connections lack (leads).
    should_sync_default: bool = True
    # OAuth scope this endpoint needs beyond the mandatory set, when we request that scope as an
    # `optional_scope` because it only exists on some HubSpot plans. HubSpot grants optional scopes
    # silently, so the source checks the connection's granted scopes before offering or syncing
    # these endpoints instead of finding out via a 403 mid-sync.
    required_scope: Optional[str] = None
    # Request every property HubSpot defines for the object rather than only the non-hs_ ones.
    # Objects whose useful properties are all hs_-prefixed (engagements, commerce) would otherwise
    # sync near-empty rows, and listing those names by hand risks requesting properties a portal
    # doesn't have. The property list is still truncated by the URL-length / search caps.
    discover_all_properties: bool = False


HUBSPOT_ENDPOINTS: dict[str, HubspotEndpointConfig] = {
    "contacts": HubspotEndpointConfig(
        name="contacts",
        path="/crm/v3/objects/contacts",
        associations=["deals", "tickets", "quotes"],
        partition_key="createdate",
        cursor_filter_property_field="lastmodifieddate",
        incremental_fields=[_incremental_field("lastmodifieddate")],
    ),
    "companies": HubspotEndpointConfig(
        name="companies",
        path="/crm/v3/objects/companies",
        associations=["contacts", "deals", "tickets", "quotes"],
        partition_key="createdate",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
    ),
    "deals": HubspotEndpointConfig(
        name="deals",
        path="/crm/v3/objects/deals",
        associations=[],
        partition_key="createdate",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
    ),
    "tickets": HubspotEndpointConfig(
        name="tickets",
        path="/crm/v3/objects/tickets",
        associations=[],
        partition_key="createdate",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
    ),
    "quotes": HubspotEndpointConfig(
        name="quotes",
        path="/crm/v3/objects/quotes",
        associations=[],
        partition_key="hs_createdate",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
    ),
    "emails": HubspotEndpointConfig(
        name="emails",
        path="/crm/v3/objects/emails",
        associations=[],
        partition_key="hs_timestamp",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
    ),
    "meetings": HubspotEndpointConfig(
        name="meetings",
        path="/crm/v3/objects/meetings",
        associations=[],
        partition_key="hs_timestamp",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
    ),
    # Leads need the `crm.objects.leads.read` scope, which existing connections weren't granted,
    # and the object must be enabled in the portal (Sales Hub Pro+). Default-disabled so existing
    # customers aren't opted in — they reconnect (picking up the scope) before enabling it.
    "leads": HubspotEndpointConfig(
        name="leads",
        path="/crm/v3/objects/leads",
        associations=[],
        partition_key="hs_createdate",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
        should_sync_default=False,
        required_scope=LEADS_SCOPE,
    ),
    # Engagement objects. HubSpot authorizes all of them (and feedback submissions) under
    # `crm.objects.contacts.read`, which every connection already holds, so they can default on.
    # `hs_timestamp` is the activity time, matching the emails and meetings entries above.
    "calls": HubspotEndpointConfig(
        name="calls",
        path="/crm/v3/objects/calls",
        associations=[],
        partition_key="hs_timestamp",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
        discover_all_properties=True,
    ),
    "notes": HubspotEndpointConfig(
        name="notes",
        path="/crm/v3/objects/notes",
        associations=[],
        partition_key="hs_timestamp",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
        discover_all_properties=True,
    ),
    "tasks": HubspotEndpointConfig(
        name="tasks",
        path="/crm/v3/objects/tasks",
        associations=[],
        partition_key="hs_timestamp",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
        discover_all_properties=True,
    ),
    "communications": HubspotEndpointConfig(
        name="communications",
        path="/crm/v3/objects/communications",
        associations=[],
        partition_key="hs_timestamp",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
        discover_all_properties=True,
    ),
    "feedback_submissions": HubspotEndpointConfig(
        name="feedback_submissions",
        path="/crm/v3/objects/feedback_submissions",
        associations=[],
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
        discover_all_properties=True,
    ),
    # Commerce and product objects. Each needs its own read scope that existing connections were
    # never granted, so they start off and only sync once the account is reconnected. They are
    # also unpartitioned: their creation-date property was not verified against a live portal, and
    # partitioning on a property a portal doesn't have would put every row in one null partition.
    "line_items": HubspotEndpointConfig(
        name="line_items",
        path="/crm/v3/objects/line_items",
        associations=["deals"],
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
        should_sync_default=False,
        discover_all_properties=True,
    ),
    "products": HubspotEndpointConfig(
        name="products",
        path="/crm/v3/objects/products",
        associations=[],
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
        should_sync_default=False,
        discover_all_properties=True,
    ),
    "invoices": HubspotEndpointConfig(
        name="invoices",
        path="/crm/v3/objects/invoices",
        associations=[],
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
        should_sync_default=False,
        discover_all_properties=True,
    ),
    "orders": HubspotEndpointConfig(
        name="orders",
        path="/crm/v3/objects/orders",
        associations=[],
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
        should_sync_default=False,
        discover_all_properties=True,
    ),
    "subscriptions": HubspotEndpointConfig(
        name="subscriptions",
        path="/crm/v3/objects/subscriptions",
        associations=[],
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
        should_sync_default=False,
        discover_all_properties=True,
    ),
    "commerce_payments": HubspotEndpointConfig(
        name="commerce_payments",
        path="/crm/v3/objects/commerce_payments",
        associations=[],
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
        should_sync_default=False,
        discover_all_properties=True,
    ),
}


@dataclass
class HubspotMetadataEndpointConfig:
    """A HubSpot lookup table that is not a CRM object: no properties, no search endpoint, and no
    server-side timestamp filter, so it is always a full refresh."""

    name: str
    primary_keys: list[str]
    # Fixed column set, taken from the endpoint's OpenAPI response schema. Rows are backfilled to
    # this set so a portal that omits an optional field doesn't shift the table's schema.
    columns: list[str]
    should_sync_default: bool = True


# Object types whose pipelines HubSpot documents. Both read with scopes existing connections hold
# (crm.objects.deals.read / tickets); anything a portal hasn't enabled is skipped on 403/404.
PIPELINE_OBJECT_TYPES = ("deals", "tickets")

_PIPELINE_COLUMNS = ["object_type", "id", "label", "displayOrder", "archived", "archivedAt", "createdAt", "updatedAt"]

HUBSPOT_METADATA_ENDPOINTS: dict[str, HubspotMetadataEndpointConfig] = {
    "pipelines": HubspotMetadataEndpointConfig(
        name="pipelines",
        # Pipeline ids are only unique within an object type ("default" names both the default
        # deal pipeline and the default ticket pipeline), so the object type is part of the key.
        primary_keys=["object_type", "id"],
        columns=_PIPELINE_COLUMNS,
    ),
    "pipeline_stages": HubspotMetadataEndpointConfig(
        name="pipeline_stages",
        primary_keys=["object_type", "pipeline_id", "id"],
        columns=[
            "object_type",
            "pipeline_id",
            "id",
            "label",
            "displayOrder",
            "archived",
            "archivedAt",
            "createdAt",
            "updatedAt",
            "metadata",
            "writePermissions",
        ],
    ),
    "properties": HubspotMetadataEndpointConfig(
        name="properties",
        primary_keys=["object_type", "name"],
        columns=[
            "object_type",
            "name",
            "label",
            "description",
            "groupName",
            "type",
            "fieldType",
            "dataSensitivity",
            "archived",
            "archivedAt",
            "calculated",
            "calculationFormula",
            "createdAt",
            "createdUserId",
            "currencyPropertyName",
            "dateDisplayHint",
            "displayOrder",
            "externalOptions",
            "formField",
            "hasUniqueValue",
            "hidden",
            "hubspotDefined",
            "modificationMetadata",
            "numberDisplayHint",
            "options",
            "referencedObjectType",
            "sensitiveDataCategories",
            "showCurrencySymbol",
            "textDisplayHint",
            "updatedAt",
            "updatedUserId",
        ],
    ),
    # Owners needs `crm.objects.owners.read`, which existing connections were never granted.
    "owners": HubspotMetadataEndpointConfig(
        name="owners",
        primary_keys=["id"],
        columns=[
            "id",
            "email",
            "firstName",
            "lastName",
            "userId",
            "userIdIncludingInactive",
            "type",
            "archived",
            "createdAt",
            "updatedAt",
            "teams",
        ],
        should_sync_default=False,
    ),
}
