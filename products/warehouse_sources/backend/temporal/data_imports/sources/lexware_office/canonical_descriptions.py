from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contacts": {
        "description": "Customers and vendors with addresses, contact details, and contact people.",
        "docs_url": "https://developers.lexware.io/docs/#contacts-endpoint",
        "columns": {"id": "Unique contact identifier.", "roles": "Customer and vendor roles and numbers."},
    },
    "articles": {
        "description": "Products and services available for sales document line items.",
        "docs_url": "https://developers.lexware.io/docs/#articles-endpoint",
        "columns": {"id": "Unique article identifier."},
    },
    "voucherlist": {
        "description": "Document summaries with type, status, dates, contact, and amounts.",
        "docs_url": "https://developers.lexware.io/docs/#voucherlist-endpoint",
        "columns": {"id": "Unique document identifier.", "createdDate": "Document creation timestamp."},
    },
    "invoices": {
        "description": "Sales invoices with line items, taxes, and payment terms.",
        "docs_url": "https://developers.lexware.io/docs/#invoices-endpoint",
    },
    "credit_notes": {
        "description": "Sales credit notes with line items and tax details.",
        "docs_url": "https://developers.lexware.io/docs/#credit-notes-endpoint",
    },
    "quotations": {
        "description": "Sales quotations with prices, optional items, and validity dates.",
        "docs_url": "https://developers.lexware.io/docs/#quotations-endpoint",
    },
    "delivery_notes": {
        "description": "Delivery documents with recipient details and delivered items.",
        "docs_url": "https://developers.lexware.io/docs/#delivery-notes-endpoint",
    },
    "order_confirmations": {
        "description": "Confirmed sales orders with items, prices, and shipping conditions.",
        "docs_url": "https://developers.lexware.io/docs/#order-confirmations-endpoint",
    },
    "down_payment_invoices": {
        "description": "Invoices requesting advance payments for sales.",
        "docs_url": "https://developers.lexware.io/docs/#down-payment-invoices-endpoint",
    },
    "vouchers": {
        "description": "Bookkeeping records for sales and purchase invoices and credit notes.",
        "docs_url": "https://developers.lexware.io/docs/#vouchers-endpoint",
    },
    "payments": {
        "description": "Payment status per document, with nested payment items.",
        "docs_url": "https://developers.lexware.io/docs/#payments-endpoint",
        "columns": {
            "voucher_id": "Document identifier from voucherlist.",
            "paymentItems": "Payments and adjustments applied to the document.",
        },
    },
}
