from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the public Orb API reference (https://docs.withorb.com/api-reference).
# Keyed by the schema/endpoint name returned by `get_schemas`.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Customers": {
        "description": "Your customers — the entities that subscribe to plans and receive invoices in Orb.",
        "docs_url": "https://docs.withorb.com/api-reference/customer/list-customers",
        "columns": {
            "id": "Orb-assigned unique identifier for the customer.",
            "external_customer_id": "Your own alias for the customer, unique within your Orb account.",
            "name": "The full name of the customer.",
            "email": "The email address of the customer.",
            "timezone": "The customer's IANA timezone, used for invoice scheduling. Cannot change after creation.",
            "payment_provider": "The external payment provider linked to the customer (e.g. stripe_invoice, netsuite).",
            "payment_provider_id": "The customer's ID in the linked payment provider.",
            "balance": "The customer's current account balance, in the customer's currency.",
            "currency": "The currency used for the customer's balance and invoices.",
            "auto_collection": "Whether invoices are automatically charged to the customer's payment method.",
            "created_at": "The creation time of the customer in Orb.",
            "metadata": "User-defined key/value pairs attached to the customer.",
        },
    },
    "Plans": {
        "description": "The pricing plans defined in your Orb catalog that customers can subscribe to.",
        "docs_url": "https://docs.withorb.com/api-reference/plan/list-plans",
        "columns": {
            "id": "Orb-assigned unique identifier for the plan.",
            "name": "The name of the plan.",
            "description": "The plan description.",
            "status": "The plan's lifecycle status: active, archived, or draft.",
            "external_plan_id": "Your own alias for the plan, unique within your Orb account.",
            "currency": "The currency the plan's prices are denominated in.",
            "created_at": "The creation time of the plan in Orb.",
        },
    },
    "Subscriptions": {
        "description": "Subscriptions linking a customer to a plan, which drive recurring billing and usage.",
        "docs_url": "https://docs.withorb.com/api-reference/subscription/list-subscriptions",
        "columns": {
            "id": "Orb-assigned unique identifier for the subscription.",
            "status": "The subscription's lifecycle status: active, ended, or upcoming.",
            "customer": "The customer the subscription belongs to.",
            "plan": "The plan the subscription is on.",
            "start_date": "The date the subscription's billing relationship started.",
            "end_date": "The date the subscription ended, if it has.",
            "current_billing_period_start_date": "Start of the current billing period.",
            "current_billing_period_end_date": "End of the current billing period.",
            "created_at": "The creation time of the subscription in Orb.",
        },
    },
    "Invoices": {
        "description": "Invoices issued to customers. Note: incremental sync is keyed on invoice_date, "
        "the only server-side timestamp filter this endpoint exposes.",
        "docs_url": "https://docs.withorb.com/api-reference/invoice/list-invoices",
        "columns": {
            "id": "Orb-assigned unique identifier for the invoice.",
            "status": "The invoice status: issued, paid, synced, void, or draft.",
            "invoice_number": "The auto-generated, customer-facing invoice number.",
            "customer": "The customer the invoice was issued to.",
            "subscription": "The subscription the invoice was generated for, if any.",
            "invoice_date": "The scheduled date of the invoice.",
            "due_date": "The date payment for the invoice is due.",
            "amount_due": "The total amount due on the invoice, in the invoice's currency.",
            "total": "The total amount of the invoice, including line items and adjustments.",
            "currency": "The currency the invoice is denominated in.",
            "created_at": "The creation time of the invoice in Orb.",
        },
    },
    "CreditNotes": {
        "description": "Credit notes that adjust or refund amounts on previously issued invoices.",
        "docs_url": "https://docs.withorb.com/api-reference/credit-note/list-credit-notes",
        "columns": {
            "id": "The Orb id of this credit note.",
            "credit_note_number": "The customer-facing credit note number.",
            "type": "The type of credit note (e.g. refund or adjustment).",
            "reason": "The reason the credit note was issued.",
            "total": "The total amount of the credit note.",
            "customer": "The customer the credit note was issued to.",
            "created_at": "The creation time of the credit note in Orb.",
            "voided_at": "The time the credit note was voided, if it has been.",
        },
    },
    "Items": {
        "description": "Items represent the things being billed for and link usage/prices to your catalog. "
        "Full refresh only — the list endpoint exposes no server-side timestamp filter.",
        "docs_url": "https://docs.withorb.com/api-reference/item/list-items",
        "columns": {
            "id": "The Orb-assigned unique identifier for the item.",
            "name": "The name of the item.",
            "external_connections": "Links between this item and external accounting/billing systems.",
            "created_at": "The time at which the item was created.",
        },
    },
    "Coupons": {
        "description": "Coupons offering discounts that can be redeemed against subscriptions. "
        "Full refresh only — the list endpoint exposes no server-side timestamp filter.",
        "docs_url": "https://docs.withorb.com/api-reference/coupon/list-coupons",
        "columns": {
            "id": "The Orb-assigned unique identifier for the coupon.",
            "redemption_code": "The code customers enter to redeem the coupon.",
            "discount": "The discount the coupon applies (percentage or amount).",
            "times_redeemed": "How many times the coupon has been redeemed.",
            "duration_in_months": "How many months the discount applies for; null means forever.",
            "max_redemptions": "The maximum number of times the coupon can be redeemed.",
            "archived_at": "The time the coupon was archived, if it has been.",
        },
    },
}
