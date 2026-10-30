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
    "Prices": {
        "description": "Prices created through Orb's price creation endpoint (e.g. add-on prices). "
        "Prices defined inside a plan are not listed here; they are in the `prices` column of the plans table. "
        "Full refresh only, because the list endpoint exposes no server-side timestamp filter.",
        "docs_url": "https://docs.withorb.com/api-reference/price/list-prices",
        "columns": {
            "id": "The Orb-assigned unique identifier for the price.",
            "external_price_id": "Your own alias for the price.",
            "name": "The name of the price.",
            "model_type": "The pricing model (e.g. unit, tiered, bulk, package, matrix).",
            "price_type": "Whether the price is a usage price, a fixed price or a composite price.",
            "cadence": "How often the price is billed (one_time, monthly, quarterly, semi_annual, annual or custom).",
            "billing_mode": "Whether the price is billed in advance or in arrears.",
            "currency": "The currency of the price.",
            "billable_metric": "The billable metric that usage prices are computed from, if any.",
            "item": "The item this price sells.",
            "fixed_price_quantity": "The quantity of a fixed price that is billed.",
            "plan_phase_order": "The order of the plan phase that the price belongs to, if any.",
            "replaces_price_id": "The price that this price replaces in plan version migrations.",
            "metadata": "User-defined key/value pairs attached to the price.",
            "created_at": "The time at which the price was created.",
        },
    },
    "BillableMetrics": {
        "description": "Billable metrics: the usage queries that usage-based prices are computed from. "
        "Full refresh only, because metric objects carry no timestamp to track.",
        "docs_url": "https://docs.withorb.com/api-reference/metric/list-metrics",
        "columns": {
            "id": "The Orb-assigned unique identifier for the billable metric.",
            "name": "The name of the billable metric.",
            "description": "A description of the billable metric.",
            "status": "The status of the metric: active, draft or archived.",
            "sql": "The SQL definition of the metric.",
            "item": "The item that the metric is associated with.",
            "metadata": "User-defined key/value pairs attached to the metric.",
        },
    },
    "CreditLedgerEntries": {
        "description": "The prepaid credit ledger for each customer: every increment, decrement, expiry, void and "
        "amendment that changed a credit balance. Synced per customer as a full refresh.",
        "docs_url": "https://docs.withorb.com/api-reference/credit/fetch-customer-credits-ledger",
        "columns": {
            "id": "The Orb-assigned unique identifier for the ledger entry.",
            "customer_id": "The Orb ID of the customer that owns the ledger entry.",
            "customer": "The customer that owns the ledger entry.",
            "entry_type": "The kind of change: increment, decrement, expiration_change, credit_block_expiry, "
            "void, void_initiated or amendment.",
            "entry_status": "Whether the entry is committed or pending.",
            "amount": "The number of credits that the entry changes.",
            "starting_balance": "The customer's credit balance before the entry.",
            "ending_balance": "The customer's credit balance after the entry.",
            "currency": "The currency or custom pricing unit of the ledger.",
            "credit_block": "The credit block that the entry affects.",
            "ledger_sequence_number": "The position of the entry in the customer's ledger.",
            "description": "An optional description of the entry.",
            "metadata": "User-defined key/value pairs attached to the entry.",
            "created_at": "The time at which the entry was added to the ledger.",
        },
    },
    "BalanceTransactions": {
        "description": "Changes to each customer's account balance, such as balance applied to invoices, "
        "credit notes and manual adjustments. Synced per customer as a full refresh.",
        "docs_url": "https://docs.withorb.com/api-reference/customer/list-balance-transactions",
        "columns": {
            "id": "A unique ID for the transaction.",
            "customer_id": "The Orb ID of the customer whose balance changed.",
            "action": "The reason for the change (e.g. applied_to_invoice, manual_adjustment, credit_note_applied).",
            "type": "Whether the transaction increments or decrements the balance.",
            "amount": "The amount by which the balance changed.",
            "starting_balance": "The customer's balance before the transaction, in the customer's currency.",
            "ending_balance": "The customer's balance after the transaction, in the customer's currency.",
            "invoice": "The invoice that the transaction relates to, if any.",
            "credit_note": "The credit note that the transaction relates to, if any.",
            "description": "An optional description for manual balance adjustments.",
            "created_at": "The creation time of the transaction.",
        },
    },
    "CreditBlocks": {
        "description": "The prepaid credit blocks of each customer in Orb's default credits ledger, including "
        "expired and depleted blocks, with their remaining balance. Blocks in a real-world currency ledger are "
        "not included. Synced per customer as a full refresh.",
        "docs_url": "https://docs.withorb.com/api-reference/credit/fetch-customer-credit-balance",
        "columns": {
            "id": "The Orb-assigned unique identifier for the credit block.",
            "customer_id": "The Orb ID of the customer that owns the credit block.",
            "balance": "The number of credits left in the block.",
            "maximum_initial_balance": "The number of credits that the block started with.",
            "credit_block_source": "How the block was created: allocation, top_up, commitment or manual.",
            "status": "Whether the block is active or waits for payment (active, pending_payment).",
            "effective_date": "The time at which the credits in the block become usable.",
            "expiry_date": "The time at which the remaining credits in the block expire.",
            "per_unit_cost_basis": "The cost basis of one credit in the block.",
            "filters": "The prices that can draw down credits from the block.",
            "metadata": "User-defined key/value pairs attached to the credit block.",
        },
    },
    "CustomerCosts": {
        "description": "A day-by-day series of each customer's costs over the current billing period (or the "
        "last active one), broken down by price. Totals are cumulative from the start of the billing period. "
        "Synced per customer as a full refresh.",
        "docs_url": "https://docs.withorb.com/api-reference/customer/fetch-customer-costs",
        "columns": {
            "customer_id": "The Orb ID of the customer that the costs belong to.",
            "timeframe_start": "The start of the window, inclusive. This is the start of the billing period.",
            "timeframe_end": "The end of the window, exclusive. Each data point moves it one day forward.",
            "subtotal": "Total costs for the window, excluding minimums and discounts.",
            "total": "Total costs for the window, including minimums and discounts.",
            "per_price_costs": "The costs for the window broken down by price, with each price's quantity, "
            "subtotal and total.",
        },
    },
    "SubscriptionCosts": {
        "description": "A day-by-day series of each subscription's costs over its current billing period (or "
        "the last active one), broken down by price. Totals are cumulative from the start of the billing "
        "period. Synced per subscription as a full refresh.",
        "docs_url": "https://docs.withorb.com/api-reference/subscription/fetch-subscription-costs",
        "columns": {
            "subscription_id": "The Orb ID of the subscription that the costs belong to.",
            "timeframe_start": "The start of the window, inclusive. This is the start of the billing period.",
            "timeframe_end": "The end of the window, exclusive. Each data point moves it one day forward.",
            "subtotal": "Total costs for the window, excluding minimums and discounts.",
            "total": "Total costs for the window, including minimums and discounts.",
            "per_price_costs": "The costs for the window broken down by price, with each price's quantity, "
            "subtotal and total.",
        },
    },
    "SubscriptionSchedules": {
        "description": "The plans of each subscription over time: the initial plan and every past and future "
        "plan change, with start and end dates. Synced per subscription as a full refresh.",
        "docs_url": "https://docs.withorb.com/api-reference/subscription/fetch-subscription-schedule",
        "columns": {
            "subscription_id": "The Orb ID of the subscription.",
            "plan": "The plan that applies in this period (id, external_plan_id and name).",
            "start_date": "The time at which the plan starts to apply to the subscription.",
            "end_date": "The time at which the plan stops to apply. Empty when the plan has no end.",
            "created_at": "The time at which the schedule entry was created.",
        },
    },
}
