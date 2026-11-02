"""Canonical, documentation-sourced descriptions for Avalara AvaTax endpoints and columns.

Sourced from the official AvaTax REST v2 reference
(https://developer.avalara.com/api-reference/avatax/rest/v2/methods/). Keyed by the resource names
in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced table. Columns
absent here fall back to LLM enrichment; coverage here is intentionally partial rather than guessed.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Audit fields AvaTax stamps on every model.
_AUDIT_COLUMNS = {
    "createdDate": "Date and time when this record was created.",
    "modifiedDate": "Date and time when this record was last modified.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_AUDIT_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Companies": {
        "description": "A company (or subsidiary) registered in your Avalara account that AvaTax calculates and reports tax for.",
        "docs_url": "https://developer.avalara.com/api-reference/avatax/rest/v2/methods/Companies/QueryCompanies/",
        "columns": _columns(
            id="Unique, account-wide identifier for the company.",
            accountId="The account this company belongs to.",
            companyCode="Unique code you use to reference this company; required to fetch its transactions.",
            name="Company legal name.",
            isActive="Whether this company can be used for tax calculation.",
            isDefault="Whether this is the default company for the account.",
        ),
    },
    "Transactions": {
        "description": "A recorded taxable action (sale, purchase, return, or inventory transfer) with its calculated tax detail.",
        "docs_url": "https://developer.avalara.com/api-reference/avatax/rest/v2/methods/Transactions/ListTransactionsByCompany/",
        "columns": _columns(
            id="Unique, account-wide identifier for the transaction.",
            code="Transaction code you assigned when the transaction was created.",
            companyId="The company this transaction was recorded against.",
            date="Date the transaction occurred.",
            status="Lifecycle status of the transaction (for example Saved, Posted, or Committed).",
            type="Document type of the transaction (for example SalesInvoice or ReturnInvoice).",
            totalAmount="Total amount of the transaction, excluding tax.",
            totalTax="Total tax calculated for the transaction.",
            customerCode="Code identifying the customer on the transaction.",
        ),
    },
    "Nexus": {
        "description": "A jurisdiction where this company has a legal obligation to collect and remit tax.",
        "docs_url": "https://developer.avalara.com/api-reference/avatax/rest/v2/methods/Nexus/ListNexusByCompany/",
        "columns": _columns(
            id="Unique identifier for the nexus declaration within its company.",
            companyId="The company this nexus declaration belongs to.",
            country="ISO 3166 country code of the jurisdiction.",
            region="State, province, or region code of the jurisdiction.",
            effectiveDate="Date this nexus declaration took effect.",
            endDate="Date this nexus declaration ended, if any.",
        ),
    },
    "Customers": {
        "description": "A customer of this company, used to apply exemptions and track exemption certificates.",
        "docs_url": "https://developer.avalara.com/api-reference/avatax/rest/v2/methods/Customers/QueryCustomers/",
        "columns": _columns(
            id="Unique identifier for the customer within its company.",
            companyId="The company this customer belongs to.",
            customerCode="Code you use to reference this customer.",
            name="Customer's name.",
        ),
    },
    "ExemptionCertificates": {
        "description": "A tax exemption certificate a customer has provided to this company.",
        "docs_url": "https://developer.avalara.com/api-reference/avatax/rest/v2/methods/Certificates/QueryCertificates/",
        "columns": _columns(
            id="Unique identifier for the certificate within its company.",
            companyId="The company this certificate was issued to.",
            exemptionNumber="Exemption number recorded on the certificate.",
        ),
    },
}
