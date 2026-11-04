import dataclasses
from typing import Optional

BASE_URL = "https://api.company-information.service.gov.uk"

# Companies House allows 600 requests per five minutes and answers 429 once that is used up.
# The shared REST client already backs off on 429, so the only tuning here is page size.
ITEMS_PER_PAGE = 100

# Connect and read timeouts, so a stalled request cannot hold an import worker open forever.
REQUEST_TIMEOUT = (10.0, 60.0)

COMPANIES = "Companies"
OFFICERS = "Officers"
PERSONS_WITH_SIGNIFICANT_CONTROL = "PersonsWithSignificantControl"
PSC_STATEMENTS = "PersonsWithSignificantControlStatements"
FILING_HISTORY = "FilingHistory"
CHARGES = "Charges"
INSOLVENCY = "Insolvency"
REGISTERS = "Registers"
EXEMPTIONS = "Exemptions"
UK_ESTABLISHMENTS = "UkEstablishments"


@dataclasses.dataclass(frozen=True)
class EndpointSpec:
    """One Companies House resource, fetched once per configured company number.

    ``path`` is formatted with the company number. ``data_selector`` names the array of rows in
    the response body; when it is ``None`` the whole body is a single row. ``total_key`` names the
    body field carrying the grand total, which is what drives offset pagination - endpoints
    without one are fetched as a single page because Companies House does not document
    ``start_index`` for them.
    """

    path: str
    primary_key: list[str]
    data_selector: Optional[str] = None
    total_key: Optional[str] = None
    # Field the company number is written onto for the rows of this endpoint. `None` means the
    # response already carries it (the company profile).
    parent_field: Optional[str] = "company_number"
    # Field to populate from the last path segment of the row's `links.self`, for resources whose
    # identifier is only exposed through that link.
    id_from_self_link: Optional[str] = None


ENDPOINT_SPECS: dict[str, EndpointSpec] = {
    COMPANIES: EndpointSpec(
        path="/company/{company_number}",
        primary_key=["company_number"],
        parent_field=None,
    ),
    OFFICERS: EndpointSpec(
        path="/company/{company_number}/officers",
        primary_key=["company_number", "appointment_id"],
        data_selector="items",
        total_key="total_results",
        id_from_self_link="appointment_id",
    ),
    PERSONS_WITH_SIGNIFICANT_CONTROL: EndpointSpec(
        path="/company/{company_number}/persons-with-significant-control",
        primary_key=["company_number", "psc_id"],
        data_selector="items",
        total_key="total_results",
        id_from_self_link="psc_id",
    ),
    PSC_STATEMENTS: EndpointSpec(
        path="/company/{company_number}/persons-with-significant-control-statements",
        primary_key=["company_number", "statement_id"],
        data_selector="items",
        total_key="total_results",
        id_from_self_link="statement_id",
    ),
    FILING_HISTORY: EndpointSpec(
        path="/company/{company_number}/filing-history",
        primary_key=["company_number", "transaction_id"],
        data_selector="items",
        total_key="total_count",
    ),
    CHARGES: EndpointSpec(
        path="/company/{company_number}/charges",
        primary_key=["company_number", "id"],
        data_selector="items",
    ),
    INSOLVENCY: EndpointSpec(
        path="/company/{company_number}/insolvency",
        primary_key=["company_number"],
    ),
    REGISTERS: EndpointSpec(
        path="/company/{company_number}/registers",
        primary_key=["company_number"],
    ),
    EXEMPTIONS: EndpointSpec(
        path="/company/{company_number}/exemptions",
        primary_key=["company_number"],
    ),
    UK_ESTABLISHMENTS: EndpointSpec(
        path="/company/{company_number}/uk-establishments",
        # Establishment rows carry their own `company_number`, so the parent lands on a
        # separate field to avoid overwriting it.
        primary_key=["parent_company_number", "company_number"],
        data_selector="items",
        parent_field="parent_company_number",
    ),
}

ENDPOINTS = tuple(ENDPOINT_SPECS.keys())

# Every table is full refresh: none of the Public Data API list endpoints accept an
# updated-since filter, so there is nothing to build a server-side incremental sync on.
INCREMENTAL_FIELDS: dict[str, list] = {}

DESCRIPTIONS: dict[str, str] = {
    COMPANIES: "Company profile for each company number you sync.",
    OFFICERS: "Current and resigned officers appointed to each company.",
    PERSONS_WITH_SIGNIFICANT_CONTROL: "People and entities with significant control over each company.",
    PSC_STATEMENTS: "Statements filed in place of a person with significant control.",
    FILING_HISTORY: "Documents filed at Companies House for each company.",
    CHARGES: "Mortgages and charges registered against each company.",
    INSOLVENCY: "Insolvency status and cases for each company.",
    REGISTERS: "Which statutory registers each company keeps at Companies House.",
    EXEMPTIONS: "Exemptions from filing person with significant control information.",
    UK_ESTABLISHMENTS: "UK establishments of each overseas company.",
}
