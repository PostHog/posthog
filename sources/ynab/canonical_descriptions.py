from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "plans": {
        "description": "YNAB plans with their names, currency formats, and available month range.",
        "docs_url": "https://api.ynab.com/v1#tag/plans",
        "columns": {"id": "Plan identifier.", "last_modified_on": "Time of the latest change to the plan."},
    },
    "accounts": {
        "description": "Accounts and their balances within each YNAB plan.",
        "docs_url": "https://api.ynab.com/v1#tag/accounts",
        "columns": {"plan_id": "Plan containing this account.", "balance": "Account balance in milliunits."},
    },
    "categories": {
        "description": "Individual categories with amounts for the current plan month in UTC.",
        "docs_url": "https://api.ynab.com/v1#tag/categories",
        "columns": {
            "plan_id": "Plan containing this category.",
            "category_group_id": "Group containing this category.",
            "balance": "Available category amount in milliunits.",
        },
    },
    "category_groups": {
        "description": "Category groups with their nested categories for the current plan month in UTC.",
        "docs_url": "https://api.ynab.com/v1#tag/categories",
        "columns": {"plan_id": "Plan containing this category group."},
    },
    "payees": {
        "description": "Payees available within each YNAB plan.",
        "docs_url": "https://api.ynab.com/v1#tag/payees",
        "columns": {"plan_id": "Plan containing this payee."},
    },
    "payee_locations": {
        "description": "Saved geographic locations associated with payees.",
        "docs_url": "https://api.ynab.com/v1#tag/payee-locations",
        "columns": {"plan_id": "Plan containing this location.", "payee_id": "Payee associated with this location."},
    },
    "months": {
        "description": "Monthly totals for income, assigned funds, and activity in each YNAB plan.",
        "docs_url": "https://api.ynab.com/v1#tag/months",
        "columns": {"plan_id": "Plan containing this month.", "month": "First day of the plan month."},
    },
    "transactions": {
        "description": "Plan transactions with nested split transactions, excluding pending transactions.",
        "docs_url": "https://api.ynab.com/v1#tag/transactions",
        "columns": {
            "plan_id": "Plan containing this transaction.",
            "amount": "Transaction amount in milliunits; negative values represent outflows.",
            "subtransactions": "Individual splits within a split transaction.",
        },
    },
    "scheduled_transactions": {
        "description": "Scheduled transactions with recurrence details and nested splits.",
        "docs_url": "https://api.ynab.com/v1#tag/scheduled-transactions",
        "columns": {"plan_id": "Plan containing this scheduled transaction.", "date_next": "Next scheduled date."},
    },
}
