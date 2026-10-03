"""Canonical, documentation-sourced descriptions for Billomat endpoints and columns.

Sourced from the official Billomat API reference (https://www.billomat.com/en/api/).
Keyed by the resource names in `settings.py` `ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Billomat table. Columns absent here fall back to LLM
enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Clients": {
        "description": "A customer you bill in Billomat.",
        "docs_url": "https://www.billomat.com/en/api/clients/",
        "columns": {
            "id": "Unique identifier for the client.",
            "created": "Time the client was created.",
            "archived": "Whether the client has been archived.",
            "client_number": "Client number shown on documents.",
            "name": "Company name.",
            "first_name": "Contact first name.",
            "last_name": "Contact last name.",
            "email": "Contact email address.",
            "phone": "Contact phone number.",
            "street": "Street address.",
            "zip": "Postal code.",
            "city": "City.",
            "country_code": "ISO 3166 alpha-2 country code.",
            "vat_number": "VAT registration number.",
            "bank_iban": "IBAN on file for the client.",
            "currency_code": "ISO currency code used for the client's documents.",
            "due_days": "Default number of days given to pay an invoice.",
            "revenue_gross": "Total gross revenue billed to the client.",
            "revenue_net": "Total net revenue billed to the client.",
        },
    },
    "Suppliers": {
        "description": "A vendor you receive bills (incomings) from in Billomat.",
        "docs_url": "https://www.billomat.com/en/api/suppliers/",
        "columns": {
            "id": "Unique identifier for the supplier.",
            "created": "Time the supplier was created.",
            "name": "Company name.",
            "first_name": "Contact first name.",
            "last_name": "Contact last name.",
            "email": "Contact email address.",
            "phone": "Contact phone number.",
            "street": "Street address.",
            "city": "City.",
            "zip": "Postal code.",
            "country_code": "ISO 3166 alpha-2 country code.",
            "vat_number": "VAT registration number.",
            "bank_iban": "IBAN on file for the supplier.",
            "currency_code": "ISO currency code used for the supplier's documents.",
            "costs_gross": "Total gross costs billed by the supplier.",
            "costs_net": "Total net costs billed by the supplier.",
        },
    },
    "Invoices": {
        "description": "An invoice issued to a client.",
        "docs_url": "https://www.billomat.com/en/api/invoices/",
        "columns": {
            "id": "Unique identifier for the invoice.",
            "client_id": "Client the invoice was issued to.",
            "invoice_number": "Invoice number, empty until the invoice is completed.",
            "status": "Invoice status: DRAFT, OPEN, PAID, OVERDUE or CANCELED.",
            "date": "Invoice date.",
            "due_date": "Payment deadline.",
            "total_gross": "Total amount including tax.",
            "total_net": "Total amount excluding tax.",
            "paid_amount": "Amount received so far.",
            "open_amount": "Outstanding balance.",
            "currency_code": "ISO currency code.",
        },
    },
    "Estimates": {
        "description": "An estimate (Billomat calls it an 'offer') sent to a client before an invoice.",
        "docs_url": "https://www.billomat.com/en/api/estimates/",
        "columns": {
            "id": "Unique identifier for the estimate.",
            "client_id": "Client the estimate was sent to.",
            "contact_id": "Contact person at the client the estimate was sent to.",
            "offer_number": "Estimate document number.",
            "status": "Estimate status: DRAFT, OPEN, WON, LOST, CANCELED or CLEARED.",
            "date": "Estimate date.",
            "total_gross": "Total amount including tax.",
            "total_net": "Total amount excluding tax.",
            "currency_code": "ISO currency code.",
            "validity_date": "Date the estimate expires.",
        },
    },
    "CreditNotes": {
        "description": "A credit note issued to a client, typically against an invoice.",
        "docs_url": "https://www.billomat.com/en/api/credit-notes/",
        "columns": {
            "id": "Unique identifier for the credit note.",
            "client_id": "Client the credit note was issued to.",
            "contact_id": "Contact person at the client the credit note was issued to.",
            "credit_note_number": "Credit note document number.",
            "date": "Credit note date.",
            "status": "Credit note status: DRAFT, OPEN or PAID.",
            "total_gross": "Total amount including tax.",
            "total_net": "Total amount excluding tax.",
            "currency_code": "ISO currency code.",
            "invoice_id": "Invoice the credit note was issued against, if any.",
        },
    },
    "Incomings": {
        "description": "An incoming bill received from a supplier.",
        "docs_url": "https://www.billomat.com/en/api/incomings/",
        "columns": {
            "id": "Unique identifier for the incoming bill.",
            "supplier_id": "Supplier the bill was received from.",
            "number": "Supplier's own document number.",
            "date": "Bill date.",
            "due_date": "Payment deadline.",
            "status": "Bill status: OPEN, PAID or OVERDUE.",
            "total_gross": "Total amount including tax.",
            "total_net": "Total amount excluding tax.",
            "paid_amount": "Amount paid so far.",
            "open_amount": "Outstanding balance.",
            "currency_code": "ISO currency code.",
            "category": "Expense category assigned to the bill.",
        },
    },
}
