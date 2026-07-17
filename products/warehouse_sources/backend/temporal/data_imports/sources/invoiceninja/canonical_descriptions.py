from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://api-docs.invoicing.co"

# Curated, docs-sourced descriptions for Invoice Ninja's core tables. Columns not covered here fall
# back to LLM enrichment. Timestamps (`created_at`, `updated_at`, `archived_at`) are integer unix
# seconds across every resource.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "clients": {
        "description": "A customer you invoice. Contacts are nested under each client as a `contacts` array.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the client.",
            "name": "The client's business or display name.",
            "balance": "Outstanding amount the client currently owes across all invoices.",
            "paid_to_date": "Total amount the client has paid to date.",
            "credit_balance": "Unapplied credit currently available to the client.",
            "contacts": "Array of the client's contacts (name, email, phone).",
            "is_deleted": "Whether the client has been soft-deleted.",
            "created_at": "Unix timestamp (seconds) when the client was created.",
            "updated_at": "Unix timestamp (seconds) when the client was last updated.",
        },
    },
    "invoices": {
        "description": "A bill sent to a client, with line items, totals, and payment status.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the invoice.",
            "client_id": "Identifier of the client the invoice was issued to.",
            "number": "Human-readable invoice number.",
            "status_id": "Lifecycle status of the invoice (draft, sent, partial, paid, etc.).",
            "amount": "Total amount of the invoice.",
            "balance": "Amount still outstanding on the invoice.",
            "paid_to_date": "Amount paid against the invoice so far.",
            "date": "Invoice date (YYYY-MM-DD).",
            "due_date": "Date the invoice is due (YYYY-MM-DD).",
            "line_items": "Array of line items on the invoice.",
            "is_deleted": "Whether the invoice has been soft-deleted.",
            "created_at": "Unix timestamp (seconds) when the invoice was created.",
            "updated_at": "Unix timestamp (seconds) when the invoice was last updated.",
        },
    },
    "quotes": {
        "description": "A proposal sent to a client that can be converted into an invoice.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the quote.",
            "client_id": "Identifier of the client the quote was issued to.",
            "number": "Human-readable quote number.",
            "status_id": "Lifecycle status of the quote (draft, sent, approved, etc.).",
            "amount": "Total amount of the quote.",
            "date": "Quote date (YYYY-MM-DD).",
            "invoice_id": "Identifier of the invoice this quote was converted into, if any.",
            "created_at": "Unix timestamp (seconds) when the quote was created.",
        },
    },
    "credits": {
        "description": "A credit note reducing what a client owes.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the credit.",
            "client_id": "Identifier of the client the credit belongs to.",
            "number": "Human-readable credit number.",
            "amount": "Total amount of the credit.",
            "balance": "Remaining unapplied balance on the credit.",
            "created_at": "Unix timestamp (seconds) when the credit was created.",
        },
    },
    "payments": {
        "description": "A payment recorded against one or more invoices.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the payment.",
            "client_id": "Identifier of the client who made the payment.",
            "amount": "Amount of the payment.",
            "refunded": "Amount of the payment that has been refunded.",
            "applied": "Amount of the payment applied to invoices.",
            "date": "Date the payment was made (YYYY-MM-DD).",
            "type_id": "Payment method used (bank transfer, credit card, etc.).",
            "transaction_reference": "External reference for the payment transaction.",
            "created_at": "Unix timestamp (seconds) when the payment was recorded.",
        },
    },
    "recurring_invoices": {
        "description": "A template that automatically generates invoices on a schedule.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the recurring invoice.",
            "client_id": "Identifier of the client billed by the recurring invoice.",
            "frequency_id": "How often invoices are generated (weekly, monthly, etc.).",
            "amount": "Amount of each generated invoice.",
            "next_send_date": "Date the next invoice will be generated (YYYY-MM-DD).",
            "remaining_cycles": "Number of invoices left to generate (-1 for unlimited).",
            "created_at": "Unix timestamp (seconds) when the recurring invoice was created.",
        },
    },
    "products": {
        "description": "A reusable catalog item that can be added to invoices and quotes.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the product.",
            "product_key": "Short code / SKU for the product.",
            "notes": "Description of the product.",
            "price": "Default unit price of the product.",
            "cost": "Cost of the product.",
            "created_at": "Unix timestamp (seconds) when the product was created.",
        },
    },
    "expenses": {
        "description": "A business expense, optionally billable to a client.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the expense.",
            "client_id": "Identifier of the client the expense is billable to, if any.",
            "vendor_id": "Identifier of the vendor the expense was paid to.",
            "category_id": "Identifier of the expense category.",
            "amount": "Amount of the expense.",
            "date": "Date the expense was incurred (YYYY-MM-DD).",
            "created_at": "Unix timestamp (seconds) when the expense was created.",
        },
    },
    "expense_categories": {
        "description": "A category used to classify expenses.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the expense category.",
            "name": "Name of the category.",
            "created_at": "Unix timestamp (seconds) when the category was created.",
        },
    },
    "vendors": {
        "description": "A supplier you pay. Contacts are nested under each vendor as a `contacts` array.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the vendor.",
            "name": "The vendor's business or display name.",
            "contacts": "Array of the vendor's contacts (name, email, phone).",
            "created_at": "Unix timestamp (seconds) when the vendor was created.",
        },
    },
    "purchase_orders": {
        "description": "An order sent to a vendor to purchase goods or services.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the purchase order.",
            "vendor_id": "Identifier of the vendor the purchase order was sent to.",
            "number": "Human-readable purchase order number.",
            "amount": "Total amount of the purchase order.",
            "status_id": "Lifecycle status of the purchase order.",
            "created_at": "Unix timestamp (seconds) when the purchase order was created.",
        },
    },
    "projects": {
        "description": "A project used to group tasks and expenses for a client.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the project.",
            "client_id": "Identifier of the client the project belongs to.",
            "name": "Name of the project.",
            "budgeted_hours": "Budgeted hours for the project.",
            "task_rate": "Default hourly rate for tasks on the project.",
            "created_at": "Unix timestamp (seconds) when the project was created.",
        },
    },
    "tasks": {
        "description": "A unit of tracked work, often billed by time, belonging to a project or client.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the task.",
            "client_id": "Identifier of the client the task belongs to.",
            "project_id": "Identifier of the project the task belongs to.",
            "description": "Description of the work.",
            "time_log": "JSON-encoded array of start/stop time entries for the task.",
            "rate": "Hourly rate applied to the task.",
            "created_at": "Unix timestamp (seconds) when the task was created.",
        },
    },
    "tax_rates": {
        "description": "A named tax rate applied to invoice and quote line items.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the tax rate.",
            "name": "Name of the tax rate.",
            "rate": "Percentage rate applied.",
            "created_at": "Unix timestamp (seconds) when the tax rate was created.",
        },
    },
    "payment_terms": {
        "description": "A reusable net payment term (e.g. Net 30) offered to clients.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the payment term.",
            "num_days": "Number of days until payment is due.",
            "created_at": "Unix timestamp (seconds) when the payment term was created.",
        },
    },
}
