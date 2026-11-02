from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Invoice": {
        "description": "Invoices issued to contacts, including payment status and totals.",
        "docs_url": "https://api.sevdesk.de/#tag/Invoice",
        "columns": {"contact": "Reference to the billed contact.", "invoiceDate": "Invoice document date."},
    },
    "InvoicePos": {
        "description": "Invoice line items with quantities, prices, discounts, and tax rates.",
        "docs_url": "https://api.sevdesk.de/#tag/InvoicePos",
        "columns": {"invoice": "Reference to the invoice.", "part": "Reference to the product."},
    },
    "Voucher": {
        "description": "Accounting receipts with supplier details, payment status, and totals.",
        "docs_url": "https://api.sevdesk.de/#tag/Voucher",
        "columns": {"voucherDate": "Receipt document date.", "supplier": "Reference to the supplier contact."},
    },
    "VoucherPos": {
        "description": "Receipt line items with accounting categories and tax amounts.",
        "docs_url": "https://api.sevdesk.de/#tag/VoucherPos",
        "columns": {"voucher": "Reference to the receipt."},
    },
    "Order": {
        "description": "Sales documents such as quotes and orders, with contacts and totals.",
        "docs_url": "https://api.sevdesk.de/#tag/Order",
        "columns": {"orderType": "Type of sales document.", "contact": "Reference to the customer contact."},
    },
    "OrderPos": {
        "description": "Order line items with products, quantities, and prices.",
        "docs_url": "https://api.sevdesk.de/#tag/OrderPos",
        "columns": {"order": "Reference to the order."},
    },
    "CreditNote": {
        "description": "Credit notes with contacts, status, and totals.",
        "docs_url": "https://api.sevdesk.de/#tag/CreditNote",
        "columns": {"creditNoteDate": "Credit note document date."},
    },
    "CreditNotePos": {
        "description": "Credit note line items with quantities, prices, and tax rates.",
        "docs_url": "https://api.sevdesk.de/#tag/CreditNotePos",
        "columns": {"creditNote": "Reference to the credit note."},
    },
    "Contact": {
        "description": "Customer and supplier contacts, including company and personal details.",
        "docs_url": "https://api.sevdesk.de/#tag/Contact",
        "columns": {"customerNumber": "Customer number assigned to the contact."},
    },
    "Part": {
        "description": "Products and services with prices, stock, and tax rates.",
        "docs_url": "https://api.sevdesk.de/#tag/Part",
        "columns": {"partNumber": "Product number."},
    },
    "CheckAccount": {
        "description": "Bank and cash accounts with currency and balance information.",
        "docs_url": "https://api.sevdesk.de/#tag/CheckAccount",
        "columns": {"currency": "Account currency."},
    },
    "CheckAccountTransaction": {
        "description": "Account transactions with amounts, dates, counterparties, and booking status.",
        "docs_url": "https://api.sevdesk.de/#tag/CheckAccountTransaction",
        "columns": {"checkAccount": "Reference to the account.", "valueDate": "Transaction value date."},
    },
}
