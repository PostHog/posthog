from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How a list endpoint is paginated:
# - "page": page-number pagination (page + numberOfItemsByPage), page index starts at 0.
# - "offset": offset pagination (start/offset + limit).
# - "single": one request, the whole collection comes back in a wrapper object.
# - "folders_tree": single request returning a nested folder tree we flatten into rows.
# - "events_window": audit log capped at 7-day windows, walked one week at a time.
# - "agreement_fanout": one request per agreement, walking the agreements list as the parent.
PaginationStyle = Literal["page", "offset", "single", "folders_tree", "events_window", "agreement_fanout"]

# Concord returns the full agreement list only when at least one stage filter is supplied, so we
# request every documented stage. Keeping this explicit (rather than relying on a default) means a
# new stage Concord adds later is a visible diff here, not a silent gap in synced data.
AGREEMENT_STATUSES = [
    "DRAFT",
    "VALIDATION",
    "NEGOTIATION",
    "SIGNING",
    "UNKNOWN_CONTRACT",
    "FUTURE_CONTRACT",
    "CURRENT_CONTRACT",
    "COMPLETED_CONTRACT",
    "COMPLETED_CANCEL_CONTRACT",
    "COMPLETED_CONTRACT_RENEWABLE",
    "BROKEN",
    "TRASHED",
    "NEGO_INVITE",
    "TEMPLATE",
    "TEMPLATE_AUTO",
]


@dataclass(frozen=False)
class ConcordEndpointConfig:
    name: str
    path: str  # may contain a `{organization_id}` placeholder
    pagination: PaginationStyle
    # Key inside the JSON response holding the row array (e.g. "items", "members"). None for
    # endpoints whose body is itself the collection wrapper handled specially (folders tree).
    data_selector: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Partition key — must be a STABLE creation-style field, never updated_at/modifiedAt.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only true where Concord exposes a genuine server-side timestamp filter for this resource.
    supports_incremental: bool = False
    # Immutable, append-only resources (the audit event log) set this so the UI offers append sync.
    supports_append: bool = False
    should_sync_default: bool = True
    # `/tags` takes the organization as a query param rather than a path segment.
    org_in_query: bool = False
    # Endpoints scoped under /organizations/{id}/ need the resolved org id; /user/me/organizations
    # does not.
    org_scoped: bool = True
    # /user/me/organizations lists every org the API key can reach. Set this so the synced rows are
    # filtered down to the single org this source is scoped to, rather than leaking every accessible
    # org's name/id into the warehouse table.
    scope_to_org: bool = False
    page_size: int = 100
    # Offset pagination uses different query param names per resource (`start` vs `offset`).
    offset_param: str = "offset"
    requires_admin: bool = False
    # Limit the first sync of an unbounded append-only resource to the last N days.
    default_lookback_days: Optional[int] = None
    # Extra query params a per-agreement child request always needs (e.g. the required `type` on
    # /activities). Only read by "agreement_fanout" endpoints.
    fanout_params: dict[str, str] = field(default_factory=dict)
    # A per-agreement endpoint answering with one object describing the agreement rather than a
    # collection, so it yields a single row keyed on the parent agreement.
    single_object_child: bool = False
    description: Optional[str] = None


_AGREEMENT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "modifiedAt",
        "type": IncrementalFieldType.DateTime,
        "field": "modifiedAt",
        "field_type": IncrementalFieldType.DateTime,
    },
    {
        "label": "createdAt",
        "type": IncrementalFieldType.DateTime,
        "field": "createdAt",
        "field_type": IncrementalFieldType.DateTime,
    },
]

_EVENT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "createdAt",
        "type": IncrementalFieldType.DateTime,
        "field": "createdAt",
        "field_type": IncrementalFieldType.DateTime,
    },
]


CONCORD_ENDPOINTS: dict[str, ConcordEndpointConfig] = {
    "organizations": ConcordEndpointConfig(
        name="organizations",
        path="/user/me/organizations",
        pagination="single",
        data_selector="organizations",
        primary_keys=["id"],
        partition_key="createdAt",
        org_scoped=False,
        scope_to_org=True,
    ),
    "agreements": ConcordEndpointConfig(
        name="agreements",
        path="/user/me/organizations/{organization_id}/agreements",
        pagination="page",
        data_selector="items",
        primary_keys=["uuid"],
        partition_key="createdAt",
        incremental_fields=_AGREEMENT_INCREMENTAL_FIELDS,
        supports_incremental=True,
        page_size=100,
    ),
    "members": ConcordEndpointConfig(
        name="members",
        path="/organizations/{organization_id}/members",
        pagination="offset",
        data_selector="members",
        # MemberDto has no `id`; `userOrganizationId` is the stable per-org member identifier.
        primary_keys=["userOrganizationId"],
        partition_key="createdAt",
        page_size=100,
        offset_param="start",
    ),
    "groups": ConcordEndpointConfig(
        name="groups",
        path="/organizations/{organization_id}/groups",
        pagination="single",
        data_selector="groups",
        primary_keys=["id"],
    ),
    "folders": ConcordEndpointConfig(
        name="folders",
        path="/organizations/{organization_id}/folders",
        pagination="folders_tree",
        primary_keys=["id"],
    ),
    "clauses": ConcordEndpointConfig(
        name="clauses",
        path="/organizations/{organization_id}/clauses",
        pagination="offset",
        data_selector="organizationClauses",
        primary_keys=["id"],
        partition_key="createdAt",
        page_size=100,
    ),
    "tags": ConcordEndpointConfig(
        name="tags",
        path="/tags",
        pagination="single",
        data_selector="tags",
        primary_keys=["id"],
        org_in_query=True,
    ),
    "reports": ConcordEndpointConfig(
        name="reports",
        path="/organizations/{organization_id}/reports",
        pagination="page",
        data_selector="reports",
        primary_keys=["id"],
        page_size=100,
    ),
    "approvals": ConcordEndpointConfig(
        name="approvals",
        path="/organizations/{organization_id}/approvals",
        pagination="single",
        data_selector="approvals",
        primary_keys=["id"],
    ),
    "events": ConcordEndpointConfig(
        name="events",
        path="/organizations/{organization_id}/events",
        pagination="events_window",
        data_selector="events",
        primary_keys=["id"],
        partition_key="createdAt",
        incremental_fields=_EVENT_INCREMENTAL_FIELDS,
        supports_incremental=True,
        supports_append=True,
        should_sync_default=False,  # admin-only endpoint; off by default so non-admins aren't blocked
        requires_admin=True,
        default_lookback_days=365,
        description="Organization audit log. Requires the Administrator role. Append only.",
    ),
    "agreement_activities": ConcordEndpointConfig(
        name="agreement_activities",
        path="/organizations/{organization_id}/agreements/{agreement_uid}/activities",
        pagination="agreement_fanout",
        data_selector="activities",
        # Activity ids are only documented as unique within their agreement, so key on the parent too.
        primary_keys=["agreement_uuid", "id"],
        partition_key="createdAt",
        # `type` is a required query param. AUDIT is the action timeline (viewed, signed, approved);
        # CHAT is the negotiation message thread, which is a different resource.
        fanout_params={"type": "AUDIT"},
        should_sync_default=False,
        description="Per-agreement audit timeline (viewed, signed, approved). One request per agreement, so it is off by default.",
    ),
    "agreement_members": ConcordEndpointConfig(
        name="agreement_members",
        path="/organizations/{organization_id}/agreements/{agreement_uid}/members",
        pagination="agreement_fanout",
        # The response body is itself the array, with no wrapper key.
        data_selector=None,
        # Rows mix active users with pending and delayed invitations; `status` separates the id
        # spaces `member_id` draws from, so all three parts are needed to stay unique.
        primary_keys=["agreement_uuid", "status", "member_id"],
        should_sync_default=False,
        description="Who has access to each agreement, with their permission and signer status. One request per agreement, so it is off by default.",
    ),
    "agreement_fields": ConcordEndpointConfig(
        name="agreement_fields",
        path="/organizations/{organization_id}/agreements/{agreement_uid}/summary/fields",
        pagination="agreement_fanout",
        data_selector="fields",
        primary_keys=["agreement_uuid", "id"],
        should_sync_default=False,
        description="Smart fields captured on each agreement, such as contract value or renewal date. One request per agreement, so it is off by default.",
    ),
    "agreement_clauses": ConcordEndpointConfig(
        name="agreement_clauses",
        # Concord has no GET for /summary/clauses — the clause instances are only listed inside the
        # agreement summary, so both clause tables read it and select a different array.
        path="/organizations/{organization_id}/agreements/{agreement_uid}/summary",
        pagination="agreement_fanout",
        data_selector="clauses",
        primary_keys=["agreement_uuid", "id"],
        should_sync_default=False,
        description="Clause instances on each agreement, joining agreements to the organization clause library. One request per agreement, so it is off by default.",
    ),
    "agreement_endclauses": ConcordEndpointConfig(
        name="agreement_endclauses",
        path="/organizations/{organization_id}/agreements/{agreement_uid}/summary",
        pagination="agreement_fanout",
        data_selector="endclauses",
        primary_keys=["agreement_uuid", "id"],
        should_sync_default=False,
        description="Renewal and termination clauses on each agreement, with notice periods and auto-renewal terms. One request per agreement, so it is off by default.",
    ),
    "agreement_approval": ConcordEndpointConfig(
        name="agreement_approval",
        path="/organizations/{organization_id}/agreements/{agreement_uid}/approval",
        pagination="agreement_fanout",
        single_object_child=True,
        primary_keys=["agreement_uuid"],
        should_sync_default=False,
        description="Approval workflow on each agreement, with its rules and current status. Joins agreements to the organization approvals library. One request per agreement, so it is off by default.",
    ),
    "agreement_signature": ConcordEndpointConfig(
        name="agreement_signature",
        path="/organizations/{organization_id}/agreements/{agreement_uid}/signature",
        pagination="agreement_fanout",
        single_object_child=True,
        primary_keys=["agreement_uuid"],
        should_sync_default=False,
        description="Signature setup and slots on each agreement, including who signed and when. One request per agreement, so it is off by default.",
    ),
    "agreement_versions": ConcordEndpointConfig(
        name="agreement_versions",
        path="/organizations/{organization_id}/agreements/{agreement_uid}/versions",
        pagination="agreement_fanout",
        # The response body is itself the array, with no wrapper key.
        data_selector=None,
        # Version ids are document ids, only documented as unique within their agreement.
        primary_keys=["agreement_uuid", "id"],
        partition_key="date",
        should_sync_default=False,
        description="Version history of each agreement, for redline and negotiation cycle analysis. One request per agreement, so it is off by default.",
    ),
    "agreement_metadata": ConcordEndpointConfig(
        name="agreement_metadata",
        path="/organizations/{organization_id}/agreements/{agreement_uid}/metadata",
        pagination="agreement_fanout",
        single_object_child=True,
        primary_keys=["agreement_uuid"],
        should_sync_default=False,
        description="Metadata on each agreement, such as its tags, track-changes setting and negotiation origin. One request per agreement, so it is off by default.",
    ),
}

ENDPOINTS = tuple(CONCORD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CONCORD_ENDPOINTS.items()
}
