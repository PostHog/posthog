from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Dataverse Web API version pinned in the request path (`/api/data/v9.2/`). Microsoft keeps older
# minor versions addressable, so this is a real version choice rather than a cosmetic `/v1/`.
DYNAMICS365_API_VERSION = "v9.2"

# Entra ID (Azure AD) v2 token endpoint. The tenant id is interpolated into the path.
DYNAMICS365_LOGIN_HOST = "login.microsoftonline.com"

# Largest page size Dataverse honours for `Prefer: odata.maxpagesize`.
DYNAMICS365_PAGE_SIZE = 5000

# (connect, read) seconds. Read is generous because a 5,000-row page of a wide table is slow to
# build server side. Dataverse's service protection limits come back as a 429 with Retry-After,
# which the tracked transport already honours, so there's no client-side throttle to configure.
DYNAMICS365_REQUEST_TIMEOUT = (10.0, 300.0)


def _tracking_fields() -> list[IncrementalField]:
    """Incremental cursor options shared by every standard Dataverse table.

    `modifiedon` and `createdon` exist on all of them and both are server-side `$filter`-able, so
    both are advertised; `modifiedon` is the default because it also catches updates.
    """
    return [incremental_field("modifiedon"), incremental_field("createdon")]


@dataclass(frozen=True)
class Dynamics365EndpointConfig:
    name: str
    # OData entity set name (the plural logical name Dataverse exposes at /api/data/<version>/).
    entity_set: str
    # Dataverse primary keys are a single GUID column named `<logical name>id`, unique table-wide.
    primary_keys: list[str]
    # Table reference page on Microsoft Learn, surfaced to the semantic-enrichment LLM.
    docs_url: str
    incremental_fields: list[IncrementalField] = field(default_factory=_tracking_fields)
    default_incremental_field: str = "modifiedon"
    # Stable creation timestamp — never `modifiedon`, which would rewrite partitions every sync.
    partition_key: str = "createdon"
    # Explicit `$select` column list. Left empty Dataverse returns every populated column, which is
    # what we want almost everywhere; it's set only for tables holding file payloads, so the sync
    # never downloads attachment bytes. Lookup columns are named without the `_..._value` wrapper
    # Dataverse uses in the response.
    select: tuple[str, ...] = ()


def _endpoint(
    name: str,
    entity_set: str,
    primary_key: str,
    docs_entity: str,
    select: tuple[str, ...] = (),
) -> Dynamics365EndpointConfig:
    return Dynamics365EndpointConfig(
        name=name,
        entity_set=entity_set,
        primary_keys=[primary_key],
        docs_url=f"https://learn.microsoft.com/en-us/dynamics365/developer/reference/entities/{docs_entity}",
        select=select,
    )


# `annotation` stores each attachment's bytes in `documentbody`, so this table is the one place we
# name the columns we want — pulling file payloads into the warehouse would be neither useful nor
# affordable.
_ANNOTATION_COLUMNS = (
    "annotationid",
    "subject",
    "notetext",
    "filename",
    "filesize",
    "mimetype",
    "isdocument",
    "objectid",
    "objecttypecode",
    "ownerid",
    "createdby",
    "modifiedby",
    "createdon",
    "modifiedon",
)


# The standard Customer Engagement tables (Sales, Customer Service, Marketing). Custom and
# unlisted tables would need discovery through the EntityDefinitions metadata API, which this
# catalog deliberately doesn't do — it keeps schema listing credential-free.
DYNAMICS365_ENDPOINTS: dict[str, Dynamics365EndpointConfig] = {
    config.name: config
    for config in (
        _endpoint("Accounts", "accounts", "accountid", "account"),
        _endpoint("Contacts", "contacts", "contactid", "contact"),
        _endpoint("Leads", "leads", "leadid", "lead"),
        _endpoint("Opportunities", "opportunities", "opportunityid", "opportunity"),
        _endpoint("Cases", "incidents", "incidentid", "incident"),
        _endpoint("Campaigns", "campaigns", "campaignid", "campaign"),
        _endpoint("Quotes", "quotes", "quoteid", "quote"),
        _endpoint("Orders", "salesorders", "salesorderid", "salesorder"),
        _endpoint("Invoices", "invoices", "invoiceid", "invoice"),
        _endpoint("Products", "products", "productid", "product"),
        _endpoint("Activities", "activitypointers", "activityid", "activitypointer"),
        _endpoint("Tasks", "tasks", "activityid", "task"),
        _endpoint("PhoneCalls", "phonecalls", "activityid", "phonecall"),
        _endpoint("Emails", "emails", "activityid", "email"),
        _endpoint("Appointments", "appointments", "activityid", "appointment"),
        _endpoint("Notes", "annotations", "annotationid", "annotation", select=_ANNOTATION_COLUMNS),
        _endpoint("Competitors", "competitors", "competitorid", "competitor"),
        _endpoint("Users", "systemusers", "systemuserid", "systemuser"),
        _endpoint("Teams", "teams", "teamid", "team"),
        _endpoint("BusinessUnits", "businessunits", "businessunitid", "businessunit"),
    )
}

ENDPOINTS = tuple(DYNAMICS365_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DYNAMICS365_ENDPOINTS.items()
}
