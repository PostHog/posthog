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
    "purchase_order_lines": {
        "description": "A single line item on a purchase order, at the grain most spend analysis aggregates.",
        "docs_url": "https://compass.coupa.com/en-us/products/core-applications/integrate/integrate-your-data/the-coupa-core-api",
        "columns": _columns(
            account="Account the line is charged to when there is no split billing.",
            account_allocations="Split billing allocations of the line across several accounts.",
            order_header_id="Identifier of the purchase order the line belongs to.",
            order_header_number="Purchase order number the line belongs to.",
            line_num="Position of the line within its purchase order.",
            sub_line_num="Position of the sub-line within its line.",
            description="Description of the goods or services ordered.",
            item="Catalog item ordered on the line.",
            commodity="Spend category the line is classified under.",
            supplier="Supplier the line is ordered from.",
            quantity="Quantity ordered on the line.",
            uom="Unit of measure of the ordered quantity.",
            price="Unit price of the line.",
            total="Total amount of the line.",
            currency="Currency of the line.",
            accounting_total="Line total converted to the accounting currency.",
            received="Quantity or amount received against the line.",
            invoiced="Amount invoiced against the line.",
            need_by_date="Date the ordered goods or services are needed by.",
            department="Department the line is charged to.",
            requester="User who requested the line.",
            contract="Contract the line is bought under.",
            match_type="Match level (two-way, three-way) the line is reconciled at.",
            type="Line type, for example quantity-based or amount-based.",
        ),
    },
    "expense_lines": {
        "description": "A single expense claimed on an expense report, with its category and account allocation.",
        "docs_url": "https://compass.coupa.com/en-us/products/core-applications/integrate/integrate-your-data/the-coupa-core-api",
        "columns": _columns(
            expense_report_id="Identifier of the expense report the line belongs to.",
            line_number="Position of the line within its expense report.",
            description="Description of the claimed expense.",
            expense_category="Expense category the line is classified under.",
            account="Account the expense is charged to.",
            account_allocations="Split allocations of the expense across several accounts.",
            merchant="Merchant the expense was incurred with.",
            expense_date="Date the expense was incurred.",
            amount="Amount claimed on the line.",
            currency="Currency the expense was incurred in.",
            approved_amount="Amount approved for reimbursement.",
            accounting_total="Line amount converted to the accounting currency.",
            reporting_total="Line amount converted to the reporting currency.",
            exchange_rate="Exchange rate applied to the line.",
            audit_status="Receipt audit outcome for the line.",
            requires_receipt="Whether a receipt is required for the line.",
            over_limit="Whether the line exceeds the policy limit for its category.",
            employee_reimbursable="Whether the line is reimbursable to the employee.",
            expensed_by="User the expense was incurred by.",
            expense_line_taxes="Tax amounts recorded against the line.",
            order_line_id="Purchase order line the expense is matched to.",
            type="Line type, for example a mileage, per diem, or standard expense.",
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
