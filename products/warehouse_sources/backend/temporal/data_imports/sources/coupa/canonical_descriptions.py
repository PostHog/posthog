"""Canonical, documentation-sourced descriptions for Coupa endpoints and columns.

Sourced from the official Coupa Core API reference (https://compass.coupa.com/en-us/products/
core-applications/integrate/integrate-your-data/the-coupa-core-api). Keyed by the endpoint names in
`settings.py` `COUPA_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced Coupa table.
Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Coupa objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "created-at": "Date and time the object was created.",
    "updated-at": "Date and time the object was last updated.",
    "created_at": "Date and time the object was created.",
    "updated_at": "Date and time the object was last updated.",
    "status": "Current status of the object in its workflow.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "invoices": {
        "description": "A supplier invoice submitted for payment in Coupa.",
        "docs_url": "https://compass.coupa.com/en-us/products/core-applications/integrate/integrate-your-data/the-coupa-core-api",
        "columns": _columns(
            **{"invoice-number": "Supplier-provided invoice number."},
            supplier="The supplier that issued the invoice.",
            **{
                "total-with-taxes": "Total invoice amount including taxes.",
                "gross-total": "Gross total amount of the invoice.",
                "net-total": "Net total amount of the invoice before taxes.",
                "tax-amount": "Total tax amount on the invoice.",
                "invoice-date": "Date the invoice was issued.",
                "paid-at": "Date and time the invoice was paid.",
                "currency": "Currency of the invoice.",
            },
        ),
    },
    "purchase_orders": {
        "description": "A purchase order issued to a supplier in Coupa.",
        "docs_url": "https://compass.coupa.com/en-us/products/core-applications/integrate/integrate-your-data/the-coupa-core-api",
        "columns": _columns(
            **{
                "po-number": "Human-readable purchase order number.",
                "order-header-num": "Order header number of the purchase order.",
                "total": "Total amount of the purchase order.",
                "currency": "Currency of the purchase order.",
                "ship-to-address": "Address the order is shipped to.",
            },
            supplier="The supplier the purchase order is issued to.",
            requisition_header="The requisition the purchase order originated from.",
            **{"order-lines": "Line items of the purchase order."},
        ),
    },
    "requisitions": {
        "description": "A purchase requisition requesting goods or services in Coupa.",
        "docs_url": "https://compass.coupa.com/en-us/products/core-applications/integrate/integrate-your-data/the-coupa-core-api",
        "columns": _columns(
            requested_by="The user who created the requisition.",
            **{
                "total": "Total amount of the requisition.",
                "currency": "Currency of the requisition.",
                "submitted-at": "Date and time the requisition was submitted for approval.",
                "requisition-lines": "Line items of the requisition.",
            },
        ),
    },
    "suppliers": {
        "description": "A supplier (vendor) that goods or services are purchased from in Coupa.",
        "docs_url": "https://compass.coupa.com/en-us/products/core-applications/integrate/integrate-your-data/the-coupa-core-api",
        "columns": _columns(
            name="Name of the supplier.",
            **{
                "display-name": "Display name of the supplier.",
                "number": "Supplier number assigned in Coupa.",
                "primary-contact": "Primary contact for the supplier.",
                "primary-address": "Primary address of the supplier.",
                "payment-term": "Default payment term for the supplier.",
                "currency": "Default transaction currency of the supplier.",
            },
        ),
    },
    "contracts": {
        "description": "A contract governing terms with a supplier in Coupa.",
        "docs_url": "https://compass.coupa.com/en-us/products/core-applications/integrate/integrate-your-data/the-coupa-core-api",
        "columns": _columns(
            name="Name of the contract.",
            **{
                "number": "Contract number assigned in Coupa.",
                "start-date": "Start date of the contract.",
                "end-date": "End date of the contract.",
                "maximum-value": "Maximum spend value allowed under the contract.",
                "currency": "Currency of the contract.",
            },
            supplier="The supplier the contract is with.",
        ),
    },
    "expense_reports": {
        "description": "An employee expense report submitted for reimbursement in Coupa.",
        "docs_url": "https://compass.coupa.com/en-us/products/core-applications/integrate/integrate-your-data/the-coupa-core-api",
        "columns": _columns(
            **{
                "expense-report-number": "Human-readable expense report number.",
                "submitted-at": "Date and time the expense report was submitted.",
                "total": "Total amount claimed in the expense report.",
                "currency": "Currency of the expense report.",
                "expense-lines": "Individual expense line items.",
            },
            **{"submitted-by": "The user who submitted the expense report."},
        ),
    },
    "users": {
        "description": "A user account within the Coupa instance.",
        "docs_url": "https://compass.coupa.com/en-us/products/core-applications/integrate/integrate-your-data/the-coupa-core-api",
        "columns": _columns(
            login="Login name of the user.",
            email="Email address of the user.",
            **{
                "firstname": "First name of the user.",
                "lastname": "Last name of the user.",
                "fullname": "Full name of the user.",
                "employee-number": "Employee number of the user.",
                "active": "Whether the user account is active.",
            },
        ),
    },
    "approvals": {
        "description": "An approval step recorded against a document in a Coupa approval chain.",
        "docs_url": "https://compass.coupa.com/en-us/products/core-applications/integrate/integrate-your-data/the-coupa-core-api",
        "columns": _columns(
            approver="The user assigned to approve the document.",
            **{
                "approval-chain-id": "Identifier of the approval chain the step belongs to.",
                "approvable-type": "Type of document being approved (e.g. requisition, invoice).",
                "approvable-id": "Identifier of the document being approved.",
                "approved-at": "Date and time the step was approved.",
                "position": "Position of the step within its approval chain.",
            },
        ),
    },
}
