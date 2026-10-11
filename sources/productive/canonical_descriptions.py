from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "bookings": {
        "description": "Scheduled work allocations and absences for people.",
        "docs_url": "https://developer.productive.io/reference/resources/bookings",
    },
    "companies": {
        "description": "Client organizations associated with projects, deals, budgets, and invoices.",
        "docs_url": "https://developer.productive.io/reference/resources/companies",
    },
    "contact_entries": {
        "description": "Email addresses, phone numbers, websites, and postal addresses belonging to companies or people.",
        "docs_url": "https://developer.productive.io/reference/resources/contact-entries",
    },
    "deals": {
        "description": "Sales opportunities and delivery budgets, including their financial and pipeline details.",
        "docs_url": "https://developer.productive.io/reference/resources/deals",
    },
    "expenses": {
        "description": "Costs other than labor recorded against budget services, including approval and reimbursement details.",
        "docs_url": "https://developer.productive.io/reference/resources/expenses",
    },
    "invoices": {
        "description": "Client billing documents and their payment and delivery status.",
        "docs_url": "https://developer.productive.io/reference/resources/invoices",
    },
    "payments": {
        "description": "Amounts received against invoices.",
        "docs_url": "https://developer.productive.io/reference/resources/payments",
    },
    "people": {
        "description": "Employees, contractors, contacts, and placeholders in the organization.",
        "docs_url": "https://developer.productive.io/reference/resources/people",
    },
    "projects": {
        "description": "Workspaces organizing client and internal work, including tasks and budgets.",
        "docs_url": "https://developer.productive.io/reference/resources/projects",
    },
    "services": {
        "description": "Deal and budget line items defining billing rates and rules for tracking work.",
        "docs_url": "https://developer.productive.io/reference/resources/services",
    },
    "tasks": {
        "description": "Assigned project work items with workflow status and links to services for time tracking.",
        "docs_url": "https://developer.productive.io/reference/resources/tasks",
    },
    "time_entries": {
        "description": "Time logged by people against services, including work dates and durations.",
        "docs_url": "https://developer.productive.io/reference/resources/time-entries",
    },
}
