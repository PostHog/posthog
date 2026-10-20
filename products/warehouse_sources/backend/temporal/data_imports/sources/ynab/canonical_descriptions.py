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
    "month_categories": {
        "description": "Categories with their assigned, activity, and available amounts for each plan month.",
        "docs_url": "https://api.ynab.com/v1#tag/months",
        "columns": {
            "plan_id": "Plan containing this category.",
            "month": "First day of the plan month that the amounts apply to.",
            "budgeted": "Amount assigned to the category in the month, in milliunits.",
            "activity": "Category activity in the month, in milliunits.",
            "balance": "Available category amount at the end of the month, in milliunits.",
        },
    },
    "money_movements": {
        "description": "Money moved between budget categories in each plan.",
        "docs_url": "https://api.ynab.com/v1#tag/money-movements",
        "columns": {
            "plan_id": "Plan containing this money movement.",
            "month": "Plan month of the money movement.",
            "moved_at": "Time the server processed the money movement.",
            "from_category_id": "Category the money was moved from.",
            "to_category_id": "Category the money was moved to.",
            "amount": "Amount moved, in milliunits.",
            "money_movement_group_id": "Group this money movement belongs to.",
            "performed_by_user_id": "User who moved the money.",
        },
    },
    "money_movement_groups": {
        "description": "Groups of related money movements, with their month, author, and note.",
        "docs_url": "https://api.ynab.com/v1#tag/money-movements",
        "columns": {
            "plan_id": "Plan containing this money movement group.",
            "group_created_at": "Time the money movement group was created.",
            "month": "Plan month of the money movement group.",
            "performed_by_user_id": "User who performed the money movement group.",
        },
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
