"""Canonical, documentation-sourced descriptions for Deel endpoints and columns.

Sourced from the official Deel API reference (https://developer.deel.com/reference). Keyed by the
endpoint names in `settings.py` `DEEL_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Deel table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "people": {
        "description": "A worker in the organization — an employee or contractor managed in Deel.",
        "docs_url": "https://developer.deel.com/reference/getpeoplelist",
        "columns": {
            "id": "Unique identifier for the person.",
            "first_name": "The person's first name.",
            "last_name": "The person's last name.",
            "full_name": "The person's full name.",
            "emails": "Email addresses associated with the person.",
            "hiring_status": "Current hiring status of the person (e.g. active, inactive).",
            "hiring_type": "Type of engagement (e.g. employee, contractor).",
            "start_date": "Date the person started with the organization.",
            "job_title": "The person's job title.",
            "country": "Country the person is based in.",
        },
    },
    "contracts": {
        "description": "A work agreement between the organization and a worker in Deel.",
        "docs_url": "https://developer.deel.com/reference/getcontractlist",
        "columns": {
            "id": "Unique identifier for the contract.",
            "title": "Title of the contract.",
            "type": "Type of contract (e.g. ongoing_time_based, pay_as_you_go, milestone, eor).",
            "status": "Current status of the contract (e.g. in_progress, completed, cancelled).",
            "created_at": "Time at which the contract was created.",
            "currency": "Currency the contract is denominated in.",
            "client_name": "Name of the client party on the contract.",
            "worker_name": "Name of the worker on the contract.",
        },
    },
    "invoices": {
        "description": "An invoice issued for a contract or payroll cycle in Deel.",
        "docs_url": "https://developer.deel.com/reference/getinvoicelist",
        "columns": {
            "id": "Unique identifier for the invoice.",
            "contract_id": "Identifier of the contract this invoice relates to.",
            "status": "Current status of the invoice (e.g. paid, pending, processing).",
            "currency": "Currency the invoice is denominated in.",
            "total": "Total amount of the invoice.",
            "issued_at": "Date the invoice was issued.",
            "paid_at": "Date the invoice was paid, if applicable.",
        },
    },
    "invoice_adjustments": {
        "description": "An adjustment (bonus, deduction, expense, etc.) applied to a Deel invoice.",
        "docs_url": "https://developer.deel.com/reference/getinvoiceadjustmentslist",
        "columns": {
            "id": "Unique identifier for the invoice adjustment.",
            "contract_id": "Identifier of the contract this adjustment relates to.",
            "type": "Type of adjustment (e.g. bonus, deduction, expense, overtime).",
            "title": "Title or description of the adjustment.",
            "amount": "Amount of the adjustment.",
            "currency": "Currency the adjustment is denominated in.",
            "status": "Current status of the adjustment.",
        },
    },
}
