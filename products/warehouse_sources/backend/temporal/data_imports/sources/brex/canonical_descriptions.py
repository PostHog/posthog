"""Canonical, documentation-sourced descriptions for Brex endpoints and columns.

Sourced from the official Brex API reference (https://developer.brex.com/openapi/).
Keyed by the endpoint names in `settings.py` `BREX_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Brex table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "card_transactions": {
        "description": "A transaction on a Brex card — a purchase, refund, or other movement on the primary card account.",
        "docs_url": "https://developer.brex.com/openapi/transactions_api/#tag/Transactions/operation/listPrimaryCardTransactions",
        "columns": {
            "id": "Unique identifier of the transaction.",
            "description": "Description of the transaction (typically the merchant name).",
            "amount": "Monetary amount of the transaction, with amount and currency.",
            "type": "Type of the transaction (e.g. PURCHASE, REFUND, CHARGEBACK).",
            "initiated_at_date": "Date the transaction was initiated.",
            "posted_at_date": "Date the transaction posted to the account.",
            "card_id": "Identifier of the card used for the transaction.",
            "merchant": "Merchant details for the transaction.",
        },
    },
    "cash_transactions": {
        "description": "A transaction on a Brex cash account — a deposit, withdrawal, or transfer.",
        "docs_url": "https://developer.brex.com/openapi/transactions_api/#tag/Transactions/operation/listCashTransactions",
        "columns": {
            "id": "Unique identifier of the transaction.",
            "account_id": "Identifier of the cash account the transaction belongs to.",
            "description": "Description of the transaction.",
            "amount": "Monetary amount of the transaction, with amount and currency.",
            "type": "Type of the transaction (e.g. BOOK_TRANSFER, ACH_TRANSFER, WIRE_TRANSFER).",
            "initiated_at_date": "Date the transaction was initiated.",
            "posted_at_date": "Date the transaction posted to the account.",
        },
    },
    "expenses": {
        "description": "An expense in Brex — a recorded spend item with receipts, status, and accounting details.",
        "docs_url": "https://developer.brex.com/openapi/expenses_api/#tag/Expenses/operation/listExpenses",
        "columns": {
            "id": "Unique identifier of the expense.",
            "memo": "Memo or description attached to the expense.",
            "status": "Current status of the expense (e.g. DRAFT, SUBMITTED, APPROVED, SETTLED).",
            "category": "Spend category assigned to the expense.",
            "merchant_id": "Identifier of the merchant for the expense.",
            "amount": "Monetary amount of the expense, with amount and currency.",
            "purchased_at": "Time at which the purchase occurred.",
            "submitted_at": "Time at which the expense was submitted.",
            "updated_at": "Time at which the expense was last updated.",
            "user_id": "Identifier of the user who incurred the expense.",
            "budget_id": "Identifier of the budget the expense is associated with.",
        },
    },
    "users": {
        "description": "A user (employee) in the Brex account.",
        "docs_url": "https://developer.brex.com/openapi/team_api/#tag/Users/operation/listUsers",
        "columns": {
            "id": "Unique identifier of the user.",
            "first_name": "First name of the user.",
            "last_name": "Last name of the user.",
            "email": "Email address of the user.",
            "status": "Account status of the user (e.g. ACTIVE, INVITED, DISABLED).",
            "manager_id": "Identifier of the user's manager.",
            "department_id": "Identifier of the department the user belongs to.",
            "location_id": "Identifier of the location the user belongs to.",
        },
    },
    "departments": {
        "description": "A department defined in the Brex account for organizing users and budgets.",
        "docs_url": "https://developer.brex.com/openapi/team_api/#tag/Departments/operation/listDepartments",
        "columns": {
            "id": "Unique identifier of the department.",
            "name": "Name of the department.",
            "description": "Description of the department.",
        },
    },
    "locations": {
        "description": "A physical location defined in the Brex account for organizing users and budgets.",
        "docs_url": "https://developer.brex.com/openapi/team_api/#tag/Locations/operation/listLocations",
        "columns": {
            "id": "Unique identifier of the location.",
            "name": "Name of the location.",
            "description": "Description of the location.",
        },
    },
    "vendors": {
        "description": "A vendor (payee) configured in Brex for bill payments.",
        "docs_url": "https://developer.brex.com/openapi/payments_api/#tag/Vendors/operation/listVendors",
        "columns": {
            "id": "Unique identifier of the vendor.",
            "name": "Name of the vendor.",
            "email": "Email address of the vendor.",
            "phone": "Phone number of the vendor.",
            "payment_accounts": "Payment account details configured for the vendor.",
        },
    },
    "budgets": {
        "description": "A budget in Brex that controls and tracks spend for a group or purpose.",
        "docs_url": "https://developer.brex.com/openapi/budgets_api/#tag/Budgets/operation/listBudgets",
        "columns": {
            "budget_id": "Unique identifier of the budget.",
            "name": "Name of the budget.",
            "description": "Description of the budget.",
            "parent_budget_id": "Identifier of the parent budget, if nested.",
            "budget_status": "Status of the budget (e.g. ACTIVE, EXPIRED).",
            "limit": "Spend limit configured for the budget, with amount and currency.",
            "spend_budget_status": "Spend status of the budget relative to its limit.",
            "period_type": "Recurrence period of the budget (e.g. MONTHLY, QUARTERLY, YEARLY, ONE_TIME).",
        },
    },
}
