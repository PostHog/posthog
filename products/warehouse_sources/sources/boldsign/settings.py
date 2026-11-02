from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

PAGE_SIZE = 100


@frozen
class BoldSignEndpointConfig:
    name: str
    path: str
    # Most list endpoints wrap their rows in a `result` array; teams uses `results`.
    data_key: str = "result"
    primary_keys: list[str] = field(default_factory=lambda: ["documentId"])
    # `brand/list` returns the full set in one response with no pagination params.
    paginated: bool = True
    # Only the document list endpoints expose a `cursor` field + `NextCursor` param to page past
    # the 10,000-record cap that page-number access is limited to. Others stay page-only.
    supports_cursor: bool = False
    # Static query params always sent for the endpoint (e.g. widening filters to "all").
    extra_params: dict[str, str] = field(default_factory=dict)
    should_sync_default: bool = True
    # Set when the endpoint is only reachable per parent row (e.g. custom fields per brand).
    fanout: DependentEndpointConfig | None = None
    # Every BoldSign endpoint is full refresh; these stay empty but satisfy the fan-out helper's
    # endpoint protocol.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    page_size: int = PAGE_SIZE


# Curated catalog of the BoldSign list endpoints a user is likely to sync. Cross-referenced
# against the public Swagger (https://api.boldsign.com/swagger/v1/swagger.json). Every endpoint
# is full refresh: the only server-side date filter BoldSign documents (the document list
# endpoints' StartDate/EndDate with DateFilterType=SentBetween) filters on the document
# *transmit* date and has no matching stable cursor field in the response, so there is no
# reliable incremental field.
BOLDSIGN_ENDPOINTS: dict[str, BoldSignEndpointConfig] = {
    "documents": BoldSignEndpointConfig(
        name="documents",
        path="/v1/document/list",
        primary_keys=["documentId"],
        supports_cursor=True,
    ),
    "team_documents": BoldSignEndpointConfig(
        name="team_documents",
        path="/v1/document/teamlist",
        primary_keys=["documentId"],
        supports_cursor=True,
        # Off by default: on a team account this is a superset of `documents`, so syncing both
        # by default would bill most rows twice.
        should_sync_default=False,
    ),
    "behalf_documents": BoldSignEndpointConfig(
        name="behalf_documents",
        path="/v1/document/behalfList",
        primary_keys=["documentId"],
        supports_cursor=True,
        # PageType has no documented server-side default, so pick one rather than depend on it.
        # BehalfOfOthers is the sense the endpoint exists for — documents the API user sent for
        # someone else. Documents others sent for the API user (BehalfOfMe) are not synced.
        extra_params={"PageType": "BehalfOfOthers"},
        should_sync_default=False,
    ),
    "templates": BoldSignEndpointConfig(
        name="templates",
        path="/v1/template/list",
        primary_keys=["documentId"],
        # Without TemplateType the API only returns the caller's own templates; "all" also
        # surfaces templates shared with the account.
        extra_params={"TemplateType": "all"},
    ),
    "users": BoldSignEndpointConfig(
        name="users",
        path="/v1/users/list",
        primary_keys=["userId"],
    ),
    "teams": BoldSignEndpointConfig(
        name="teams",
        path="/v1/teams/list",
        data_key="results",
        primary_keys=["teamId"],
    ),
    "contacts": BoldSignEndpointConfig(
        name="contacts",
        path="/v1/contacts/list",
        primary_keys=["id"],
        extra_params={"ContactType": "AllContacts"},
    ),
    "contact_groups": BoldSignEndpointConfig(
        name="contact_groups",
        path="/v1/contactGroups/list",
        primary_keys=["groupId"],
        extra_params={"ContactType": "AllContacts"},
    ),
    "sender_identities": BoldSignEndpointConfig(
        name="sender_identities",
        path="/v1/senderIdentities/list",
        primary_keys=["id"],
    ),
    "brands": BoldSignEndpointConfig(
        name="brands",
        path="/v1/brand/list",
        primary_keys=["brandId"],
        paginated=False,
    ),
    "custom_fields": BoldSignEndpointConfig(
        name="custom_fields",
        # brandId is a required query param, so it is bound into the path by the fan-out.
        path="/v1/customField/list?brandId={brandId}",
        primary_keys=["brandId", "customFieldId"],
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="brands",
            resolve_param="brandId",
            resolve_field="brandId",
            # The response's own brandId is nullable, so take the parent's value — it is half of
            # the primary key.
            include_from_parent=["brandId"],
            parent_field_renames={"brandId": "brandId"},
        ),
    ),
}

ENDPOINTS = tuple(BOLDSIGN_ENDPOINTS.keys())
