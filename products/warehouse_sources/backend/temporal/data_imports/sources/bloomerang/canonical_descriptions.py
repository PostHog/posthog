"""Canonical, documentation-sourced descriptions for Bloomerang v2 endpoints and columns.

Bloomerang's REST API v2 has no public OpenAPI/Swagger page that renders without JavaScript, so
these descriptions are sourced from the field comments in a maintained third-party client that
mirrors the vendor's own API reference (https://bloomerang.co/features/integrations/api/rest-api),
cross-checked against the vendor's own admin help docs (https://bloomerang.com/api). Keyed by the
resource names in `settings.py` `ENDPOINTS`. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://bloomerang.com/api/rest-api"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Constituents": {
        "description": "An individual, household, or organization tracked in the Bloomerang donor database.",
        "docs_url": _DOCS_URL,
        "columns": {
            "Id": "Unique identifier for the constituent used by the API.",
            "AccountNumber": "User-friendly account number shown in the Bloomerang CRM UI.",
            "Type": "Whether the constituent is an Individual or an Organization.",
            "Status": "Whether the constituent is Active, Inactive, or Deceased.",
            "FirstName": "Constituent's first name.",
            "LastName": "Constituent's last name.",
            "FullName": "Constituent's full display name.",
            "Employer": "Name of the constituent's employer.",
            "HouseholdId": "ID of the household this constituent belongs to, if any.",
            "PrimaryEmail": "The constituent's primary email address record.",
            "PrimaryPhone": "The constituent's primary phone number record.",
            "PrimaryAddress": "The constituent's primary mailing address record.",
            "EngagementScore": "Bloomerang's calculated donor engagement level (Low through High).",
            "CreatedDate": "When the constituent record was created, flattened from AuditTrail.",
            "LastModifiedDate": "When the constituent record was last modified, flattened from AuditTrail.",
        },
    },
    "Transactions": {
        "description": "A donation, pledge, pledge payment, or recurring donation payment recorded against a constituent.",
        "docs_url": _DOCS_URL,
        "columns": {
            "Id": "Unique identifier for the transaction used by the API.",
            "TransactionNumber": "User-friendly payment number shown in the Bloomerang CRM UI.",
            "AccountId": "ID of the constituent the transaction is recorded against.",
            "Date": "Date the transaction took place.",
            "Amount": "Transaction amount.",
            "Method": "Payment method (Cash, Check, CreditCard, Eft, InKind, or None).",
            "Designations": "The fund/campaign/appeal splits this transaction's amount is allocated across.",
            "IsRefunded": "Whether the transaction has been refunded (Yes or No).",
            "CreatedDate": "When the transaction record was created, flattened from AuditTrail.",
            "LastModifiedDate": "When the transaction record was last modified, flattened from AuditTrail.",
        },
    },
    "Interactions": {
        "description": "A logged touchpoint with a constituent, such as an email, call, or in-person visit.",
        "docs_url": _DOCS_URL,
        "columns": {
            "Id": "Unique identifier for the interaction used by the API.",
            "Date": "Date the interaction took place.",
            "Note": "Free-text note describing the interaction.",
            "Channel": "Communication channel used (Email, Phone, Mail, InPerson, and others).",
            "Purpose": "Reason for the interaction (Acknowledgement, Solicitation, Newsletter, and others).",
            "Subject": "Subject line or short title of the interaction.",
            "IsInbound": "Whether the interaction was initiated by the constituent rather than the org.",
            "AccountId": "ID of the constituent the interaction is recorded against.",
            "CreatedDate": "When the interaction record was created, flattened from AuditTrail.",
            "LastModifiedDate": "When the interaction record was last modified, flattened from AuditTrail.",
        },
    },
    "Appeals": {
        "description": "A fundraising appeal (a specific ask sent to donors) that transactions can be designated to.",
        "docs_url": _DOCS_URL,
        "columns": {
            "Id": "Unique identifier for the appeal used by the API.",
            "Name": "Name of the appeal.",
            "SortIndex": "Manual sort position for the appeal in the Bloomerang CRM UI.",
            "IsActive": "Whether the appeal is currently active.",
        },
    },
    "Campaigns": {
        "description": "A fundraising campaign that groups appeals and transactions toward a shared goal.",
        "docs_url": _DOCS_URL,
        "columns": {
            "Id": "Unique identifier for the campaign used by the API.",
            "Name": "Name of the campaign.",
            "Raised": "Total amount raised for this campaign so far.",
            "Goal": "Fundraising goal amount for the campaign.",
            "StartDate": "Date the campaign starts.",
            "EndDate": "Date the campaign ends.",
            "IsActive": "Whether the campaign is currently active.",
        },
    },
    "Funds": {
        "description": "A designation fund (general ledger bucket) that transactions can be allocated to.",
        "docs_url": _DOCS_URL,
        "columns": {
            "Id": "Unique identifier for the fund used by the API.",
            "Name": "Name of the fund.",
            "IsDefault": "Whether this is the default fund for undesignated transactions.",
            "IsActive": "Whether the fund is currently active.",
        },
    },
}
