from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "invoices": {
        "description": "Sales invoices with line items, taxes, payments, and outstanding balances.",
        "docs_url": "https://developer.alegra.com/reference/get_invoices",
        "columns": {
            "id": "Unique identifier of the sales invoice.",
            "date": "Invoice document date.",
            "dueDate": "Invoice payment due date.",
            "total": "Total invoice amount.",
            "totalPaid": "Amount paid against the invoice.",
            "balance": "Outstanding invoice balance.",
        },
    },
    "contacts": {
        "description": "Customers and suppliers with contact details and accounting information.",
        "docs_url": "https://developer.alegra.com/reference/listcontacts-1",
        "columns": {
            "id": "Unique identifier of the contact.",
            "type": "Contact roles: client, provider, or both.",
            "identification": "Tax or personal identification number of the contact.",
        },
    },
    "items": {
        "description": "Products and services with prices, taxes, and inventory details.",
        "docs_url": "https://developer.alegra.com/reference/get_items",
        "columns": {
            "id": "Unique identifier of the product or service.",
            "reference": "Product or service reference.",
            "inventory": "Inventory quantities, units, costs, and warehouses.",
        },
    },
    "incoming_payments": {
        "description": "Received payments and their associated invoices, contacts, and bank accounts.",
        "docs_url": "https://developer.alegra.com/reference/get_payments-1",
        "columns": {"id": "Unique identifier of the payment.", "date": "Payment document date."},
    },
    "outgoing_payments": {
        "description": "Outgoing payments and their associated purchase documents and bank accounts.",
        "docs_url": "https://developer.alegra.com/reference/get_payments-1",
        "columns": {"id": "Unique identifier of the payment.", "date": "Payment document date."},
    },
    "bills": {
        "description": "Supplier bills with purchase details, taxes, payments, and outstanding balances.",
        "docs_url": "https://developer.alegra.com/reference/get_bills",
        "columns": {
            "id": "Unique identifier of the supplier bill.",
            "date": "Supplier bill document date.",
            "provider": "Supplier associated with the bill.",
        },
    },
    "estimates": {
        "description": "Sales quotations with customers, line items, prices, and taxes.",
        "docs_url": "https://developer.alegra.com/reference/get_estimates",
        "columns": {"id": "Unique identifier of the quotation.", "date": "Quotation document date."},
    },
    "credit_notes": {
        "description": "Customer credit notes, associated sales invoices, and refunds.",
        "docs_url": "https://developer.alegra.com/reference/get_credit-notes",
        "columns": {"id": "Unique identifier of the credit note.", "date": "Credit note document date."},
    },
    "debit_notes": {
        "description": "Supplier debit notes and their associated purchase documents.",
        "docs_url": "https://developer.alegra.com/reference/get_debit-notes",
        "columns": {"id": "Unique identifier of the debit note.", "date": "Debit note document date."},
    },
}
