from dataclasses import dataclass, field


@dataclass
class BoldSignEndpointConfig:
    name: str
    path: str
    # Most list endpoints wrap their rows in a `result` array; teams uses `results`.
    data_key: str = "result"
    primary_keys: list[str] = field(default_factory=lambda: ["documentId"])
    # `brand/list` returns the full set in one response with no pagination params.
    paginated: bool = True
    # Only `document/list` exposes a `cursor` field + `NextCursor` param to page past the
    # 10,000-record cap that page-number access is limited to. Other endpoints stay page-only.
    supports_cursor: bool = False
    # Static query params always sent for the endpoint (e.g. widening filters to "all").
    extra_params: dict[str, str] = field(default_factory=dict)
    should_sync_default: bool = True


# Curated catalog of the BoldSign list endpoints a user is likely to sync. Cross-referenced
# against the public Swagger (https://api.boldsign.com/swagger/v1/swagger.json). Every endpoint
# is full refresh: the only server-side date filter BoldSign documents (document/list's
# StartDate/EndDate with DateFilterType=SentBetween) filters on the document *transmit* date and
# has no matching stable cursor field in the response, so there is no reliable incremental field.
BOLDSIGN_ENDPOINTS: dict[str, BoldSignEndpointConfig] = {
    "documents": BoldSignEndpointConfig(
        name="documents",
        path="/v1/document/list",
        primary_keys=["documentId"],
        supports_cursor=True,
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
}

ENDPOINTS = tuple(BOLDSIGN_ENDPOINTS.keys())
