"""Canonical, documentation-sourced descriptions for Checkout.com endpoints and columns.

Sourced from the official Checkout.com API reference (https://api-reference.checkout.com/).
Keyed by the schema names `get_schemas` returns: the endpoint names in `checkout_com.py`
`ENDPOINTS`, plus the reports tables from `reports.py` (`reports` and the per-type
`{type}_report` tables). Report file columns are account-configurable, so `{type}_report`
entries only describe the injected metadata columns; the rest fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Every `{type}_report` table carries these columns, injected from the report listing
# alongside the report file's own columns.
_REPORT_ROWS_METADATA_COLUMNS: dict[str, str] = {
    "report_id": "Identifier of the generated report this row was parsed from.",
    "report_created_on": "Time at which the report was generated. Used as the incremental sync cursor.",
    "report_from": "Start of the date range the report covers.",
    "report_to": "End of the date range the report covers.",
    "report_entity_id": "Identifier of the entity the report belongs to.",
    "file_id": "Identifier of the report file this row was parsed from.",
    "file_row_index": "Position of this row within the report file.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "disputes": {
        "description": "A dispute (chargeback) raised by a cardholder against a Checkout.com payment.",
        "docs_url": "https://api-reference.checkout.com/#tag/Disputes",
        "columns": {
            "id": "Unique identifier for the dispute.",
            "category": "Category of the dispute (e.g. fraudulent, product_service_not_received).",
            "status": "Current status of the dispute (e.g. evidence_required, evidence_under_review, won, lost).",
            "amount": "Disputed amount, in the smallest currency unit.",
            "currency": "Three-letter ISO currency code of the dispute.",
            "reason_code": "Card scheme reason code for the dispute.",
            "resolved_reason": "Reason the dispute was resolved, once resolved.",
            "payment_id": "Identifier of the payment that was disputed.",
            "payment_reference": "Reference of the disputed payment.",
            "payment_arn": "Acquirer reference number of the disputed payment.",
            "payment_method": "Payment method used for the disputed payment.",
            "received_on": "Time at which the dispute was received.",
            "last_update": "Time at which the dispute was last updated.",
            "evidence_required_by": "Deadline by which evidence must be submitted.",
        },
    },
    "reports": {
        "description": "A report generated for your account via the Checkout.com Reports API, with the files it contains.",
        "docs_url": "https://api-reference.checkout.com/#tag/Reports",
        "columns": {
            "id": "Unique identifier for the report.",
            "created_on": "Time at which the report was generated.",
            "last_modified_on": "Time at which the report was last modified.",
            "type": "Type of the report (e.g. FinancialActions).",
            "description": "Description of the report.",
            "account": "Account the report belongs to (client and entity identifiers).",
            "tags": "Tags associated with the report.",
            "from": "Start of the date range the report covers.",
            "to": "End of the date range the report covers.",
            "files": "Files the report contains (identifier, filename, format).",
        },
    },
    "financial_actions_report": {
        "description": "Rows parsed from generated Financial Actions report files: one row per financial action (captures, refunds, chargebacks, fees) with processing and payout details.",
        "docs_url": "https://www.checkout.com/docs/business-operations/retrieve-reports",
        "columns": _REPORT_ROWS_METADATA_COLUMNS,
    },
}
