"""Canonical, documentation-sourced descriptions for Sage Intacct endpoints and columns.

Sourced from the Sage Intacct REST API reference (https://developer.sage.com/intacct/). Keyed by the
endpoint names in `settings.py` `SAGE_INTACCT_ENDPOINTS`, which match the `ExternalDataSchema.name` of
a synced Sage Intacct table. Column names are the flattened form the source emits (`audit.createdBy`
arrives as `audit_createdBy`). Every company can extend an object with custom fields, so coverage here
is deliberately limited to the standard model; anything else falls back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
    CanonicalEndpoint,
)

_DOCS_URL = "https://developer.sage.com/intacct/"

# Sage stamps every standard object with the same record key and audit block.
_SHARED_COLUMNS: dict[str, str] = {
    "key": "Immutable system-assigned record key, unique within the object.",
    "id": "User-facing identifier or document number for the record.",
    "status": "Record status, typically active or inactive.",
    "audit_createdDateTime": "Timestamp the record was created.",
    "audit_modifiedDateTime": "Timestamp the record was last modified.",
    "audit_createdBy": "User key of whoever created the record.",
    "audit_modifiedBy": "User key of whoever last modified the record.",
}


def _entry(description: str, columns: dict[str, str] | None = None) -> CanonicalEndpoint:
    return CanonicalEndpoint(
        description=description,
        docs_url=_DOCS_URL,
        columns={**_SHARED_COLUMNS, **(columns or {})},
    )


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "gl_accounts": _entry(
        "A general ledger account in the chart of accounts, used to classify every posted transaction.",
        {"name": "Title of the general ledger account."},
    ),
    "journal_entries": _entry(
        "A journal entry header: a batch of debits and credits posted to the general ledger.",
    ),
    "journal_entry_lines": _entry(
        "A single debit or credit line belonging to a journal entry.",
    ),
    "ap_bills": _entry(
        "An accounts payable bill: an amount owed to a vendor.",
    ),
    "ap_payments": _entry(
        "A payment made against one or more accounts payable bills.",
    ),
    "vendors": _entry(
        "A vendor the company buys from and pays.",
        {"name": "Vendor name."},
    ),
    "ar_invoices": _entry(
        "An accounts receivable invoice: an amount owed by a customer.",
    ),
    "ar_payments": _entry(
        "A payment received against one or more accounts receivable invoices.",
    ),
    "customers": _entry(
        "A customer the company sells to and invoices.",
        {"name": "Customer name."},
    ),
    "departments": _entry(
        "A department dimension, used to tag transactions for reporting.",
        {"name": "Department name."},
    ),
    "locations": _entry(
        "A location dimension or entity, used to tag transactions for reporting.",
        {"name": "Location name."},
    ),
    "employees": _entry(
        "An employee record, used for expenses, timesheets, and dimension tagging.",
        {"name": "Employee name."},
    ),
}
