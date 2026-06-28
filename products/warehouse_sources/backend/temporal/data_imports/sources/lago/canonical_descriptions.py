from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the public Lago API reference (https://docs.getlago.com/api-reference). Partial
# coverage is fine — any endpoint, column, or table-level description not listed here falls back to
# LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "customers": {
        "description": "A customer billed through Lago, including billing configuration and address.",
        "docs_url": "https://docs.getlago.com/api-reference/customers/object",
        "columns": {
            "lago_id": "Lago's globally-unique identifier for the customer.",
            "external_id": "The customer identifier from your own system.",
            "name": "Display name of the customer.",
            "email": "Primary billing email address of the customer.",
            "currency": "Default billing currency for the customer (ISO 4217).",
            "country": "Two-letter ISO country code for the customer's billing address.",
            "created_at": "Timestamp at which the customer was created in Lago.",
        },
    },
    "subscriptions": {
        "description": "A customer's subscription to a plan, tracking its lifecycle and billing period.",
        "docs_url": "https://docs.getlago.com/api-reference/subscriptions/object",
        "columns": {
            "lago_id": "Lago's globally-unique identifier for the subscription.",
            "external_id": "The subscription identifier from your own system.",
            "external_customer_id": "Identifier of the subscribed customer in your system.",
            "plan_code": "Code of the plan the customer is subscribed to.",
            "status": "Lifecycle status of the subscription (e.g. active, pending, terminated, canceled).",
            "started_at": "Timestamp at which the subscription started.",
            "created_at": "Timestamp at which the subscription was created in Lago.",
        },
    },
    "invoices": {
        "description": "An invoice issued to a customer for a billing period, with totals and status.",
        "docs_url": "https://docs.getlago.com/api-reference/invoices/object",
        "columns": {
            "lago_id": "Lago's globally-unique identifier for the invoice.",
            "number": "Human-readable invoice number.",
            "issuing_date": "Date the invoice was issued.",
            "payment_status": "Payment status of the invoice (e.g. pending, succeeded, failed).",
            "status": "Finalization status of the invoice (e.g. draft, finalized, voided).",
            "currency": "Currency of the invoice (ISO 4217).",
            "total_amount_cents": "Total amount due on the invoice, in the currency's smallest unit.",
            "created_at": "Timestamp at which the invoice was created in Lago.",
        },
    },
    "plans": {
        "description": "A pricing plan defining how customers subscribed to it are charged.",
        "docs_url": "https://docs.getlago.com/api-reference/plans/object",
        "columns": {
            "lago_id": "Lago's globally-unique identifier for the plan.",
            "code": "Unique code used to reference the plan.",
            "name": "Display name of the plan.",
            "interval": "Billing interval of the plan (e.g. weekly, monthly, quarterly, yearly).",
            "amount_cents": "Recurring plan amount, in the currency's smallest unit.",
            "amount_currency": "Currency of the plan amount (ISO 4217).",
            "created_at": "Timestamp at which the plan was created in Lago.",
        },
    },
    "billable_metrics": {
        "description": "A metric definition describing how usage events are aggregated for billing.",
        "docs_url": "https://docs.getlago.com/api-reference/billable-metrics/object",
        "columns": {
            "lago_id": "Lago's globally-unique identifier for the billable metric.",
            "code": "Unique code used to reference the billable metric.",
            "name": "Display name of the billable metric.",
            "aggregation_type": "How matching events are aggregated (e.g. count_agg, sum_agg, max_agg).",
            "field_name": "Event property aggregated when the aggregation type requires one.",
            "created_at": "Timestamp at which the billable metric was created in Lago.",
        },
    },
    "coupons": {
        "description": "A discount that can be applied to a customer's invoices.",
        "docs_url": "https://docs.getlago.com/api-reference/coupons/object",
        "columns": {
            "lago_id": "Lago's globally-unique identifier for the coupon.",
            "code": "Unique code used to reference the coupon.",
            "name": "Display name of the coupon.",
            "coupon_type": "Whether the coupon applies a fixed amount or a percentage discount.",
            "created_at": "Timestamp at which the coupon was created in Lago.",
        },
    },
    "applied_coupons": {
        "description": "A coupon applied to a specific customer, tracking the remaining discount.",
        "docs_url": "https://docs.getlago.com/api-reference/applied-coupons/object",
        "columns": {
            "lago_id": "Lago's globally-unique identifier for the applied coupon.",
            "lago_coupon_id": "Identifier of the coupon that was applied.",
            "external_customer_id": "Identifier of the customer the coupon was applied to, in your system.",
            "status": "Whether the applied coupon is still active or has been fully consumed.",
            "created_at": "Timestamp at which the coupon was applied.",
        },
    },
    "add_ons": {
        "description": "A one-off charge that can be added to a customer's invoice.",
        "docs_url": "https://docs.getlago.com/api-reference/add-ons/object",
        "columns": {
            "lago_id": "Lago's globally-unique identifier for the add-on.",
            "code": "Unique code used to reference the add-on.",
            "name": "Display name of the add-on.",
            "amount_cents": "Add-on amount, in the currency's smallest unit.",
            "amount_currency": "Currency of the add-on amount (ISO 4217).",
            "created_at": "Timestamp at which the add-on was created in Lago.",
        },
    },
    "credit_notes": {
        "description": "A credit note issued against an invoice, refunding or crediting a customer.",
        "docs_url": "https://docs.getlago.com/api-reference/credit-notes/object",
        "columns": {
            "lago_id": "Lago's globally-unique identifier for the credit note.",
            "number": "Human-readable credit note number.",
            "lago_invoice_id": "Identifier of the invoice the credit note was issued against.",
            "credit_status": "Status of the credited portion of the credit note.",
            "refund_status": "Status of the refunded portion of the credit note.",
            "total_amount_cents": "Total value of the credit note, in the currency's smallest unit.",
            "created_at": "Timestamp at which the credit note was created in Lago.",
        },
    },
    "fees": {
        "description": "An individual charge line generated from usage, a plan, or an add-on.",
        "docs_url": "https://docs.getlago.com/api-reference/fees/object",
        "columns": {
            "lago_id": "Lago's globally-unique identifier for the fee.",
            "lago_invoice_id": "Identifier of the invoice the fee belongs to, if any.",
            "fee_type": "Type of fee (e.g. charge, subscription, add_on, credit).",
            "amount_cents": "Fee amount, in the currency's smallest unit.",
            "amount_currency": "Currency of the fee amount (ISO 4217).",
            "created_at": "Timestamp at which the fee was created in Lago.",
        },
    },
}
