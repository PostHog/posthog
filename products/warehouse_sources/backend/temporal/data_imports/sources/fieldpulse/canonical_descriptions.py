from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "customers": {
        "description": "Customers for whom the company performs work.",
        "docs_url": "https://help.fieldpulse.com/api-reference/customers/retrieve-customers-list",
        "columns": {},
    },
    "jobs": {
        "description": "Work orders for customers, with scheduling and status information.",
        "docs_url": "https://help.fieldpulse.com/api-reference/jobs/retrieve-jobs-list",
        "columns": {},
    },
    "estimates": {
        "description": "Customer proposals that can become invoices.",
        "docs_url": "https://help.fieldpulse.com/api-reference/estimates/retrieve-estimates-list",
        "columns": {},
    },
    "invoices": {
        "description": "Invoices sent to customers to collect payment for work.",
        "docs_url": "https://help.fieldpulse.com/api-reference/invoices/list-invoices",
        "columns": {},
    },
    "payments": {
        "description": "Payments recorded against invoices.",
        "docs_url": "https://help.fieldpulse.com/api-reference/payments/retrieve-payments-list",
        "columns": {},
    },
    "projects": {
        "description": "Projects that group related jobs, estimates, and invoices.",
        "docs_url": "https://help.fieldpulse.com/api-reference/projects/retrieve-projects-list",
        "columns": {},
    },
}
