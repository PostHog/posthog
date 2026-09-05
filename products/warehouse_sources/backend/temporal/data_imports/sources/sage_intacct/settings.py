from dataclasses import dataclass

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField


@dataclass(frozen=True)
class SageIntacctEndpointConfig:
    name: str
    # Sage Intacct REST object path, e.g. "general-ledger/account". Used both as the
    # `object` in a query-service body and as the `/objects/<object>` REST path.
    object_name: str
    # `key` is Sage's immutable per-object record key; `id` is the user-editable document
    # number, so `key` is the only safe merge key.
    primary_key: str = "key"


SAGE_INTACCT_ENDPOINTS: dict[str, SageIntacctEndpointConfig] = {
    "gl_accounts": SageIntacctEndpointConfig(name="gl_accounts", object_name="general-ledger/account"),
    "journal_entries": SageIntacctEndpointConfig(name="journal_entries", object_name="general-ledger/journal-entry"),
    "journal_entry_lines": SageIntacctEndpointConfig(
        name="journal_entry_lines", object_name="general-ledger/journal-entry-line"
    ),
    "ap_bills": SageIntacctEndpointConfig(name="ap_bills", object_name="accounts-payable/bill"),
    "ap_payments": SageIntacctEndpointConfig(name="ap_payments", object_name="accounts-payable/payment"),
    "vendors": SageIntacctEndpointConfig(name="vendors", object_name="accounts-payable/vendor"),
    "ar_invoices": SageIntacctEndpointConfig(name="ar_invoices", object_name="accounts-receivable/invoice"),
    "ar_payments": SageIntacctEndpointConfig(name="ar_payments", object_name="accounts-receivable/payment"),
    "customers": SageIntacctEndpointConfig(name="customers", object_name="accounts-receivable/customer"),
    "departments": SageIntacctEndpointConfig(name="departments", object_name="company-config/department"),
    "locations": SageIntacctEndpointConfig(name="locations", object_name="company-config/location"),
    "employees": SageIntacctEndpointConfig(name="employees", object_name="company-config/employee"),
}

ENDPOINTS = tuple(SAGE_INTACCT_ENDPOINTS.keys())

# Sage stamps every standard object with an `audit` block. Rows arrive flattened
# (`audit_modifiedDateTime`), while the query service filters and sorts on the dotted path
# (`audit.modifiedDateTime`), so the two spellings have to be mapped explicitly.
INCREMENTAL_FIELD_QUERY_PATHS: dict[str, str] = {
    "audit_modifiedDateTime": "audit.modifiedDateTime",
    "audit_createdDateTime": "audit.createdDateTime",
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        incremental_field("audit_modifiedDateTime"),
        incremental_field("audit_createdDateTime"),
    ]
    for name in SAGE_INTACCT_ENDPOINTS
}
