ACCOUNT_RESOURCE_NAME = "Account"
BALANCE_TRANSACTION_RESOURCE_NAME = "BalanceTransaction"
CHARGE_RESOURCE_NAME = "Charge"
CUSTOMER_RESOURCE_NAME = "Customer"
DISPUTE_RESOURCE_NAME = "Dispute"
INVOICE_ITEM_RESOURCE_NAME = "InvoiceItem"
INVOICE_RESOURCE_NAME = "Invoice"
PAYOUT_RESOURCE_NAME = "Payout"
PRICE_RESOURCE_NAME = "Price"
PRODUCT_RESOURCE_NAME = "Product"
REFUND_RESOURCE_NAME = "Refund"
SUBSCRIPTION_RESOURCE_NAME = "Subscription"
CREDIT_NOTE_RESOURCE_NAME = "CreditNote"
CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME = "CustomerBalanceTransaction"
CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME = "CustomerPaymentMethod"
CUSTOMER_PAYMENT_METHOD_HISTORY_RESOURCE_NAME = "CustomerPaymentMethodHistory"
COUPON_RESOURCE_NAME = "Coupon"
DISCOUNT_RESOURCE_NAME = "Discount"
PAYMENT_INTENT_RESOURCE_NAME = "PaymentIntent"
CHECKOUT_SESSION_RESOURCE_NAME = "CheckoutSession"
SUBSCRIPTION_ITEM_RESOURCE_NAME = "SubscriptionItem"
SUBSCRIPTION_SCHEDULE_RESOURCE_NAME = "SubscriptionSchedule"
PROMOTION_CODE_RESOURCE_NAME = "PromotionCode"
PLAN_RESOURCE_NAME = "Plan"
TAX_RATE_RESOURCE_NAME = "TaxRate"
TAX_ID_RESOURCE_NAME = "TaxId"
QUOTE_RESOURCE_NAME = "Quote"
EVENT_RESOURCE_NAME = "Event"
BILLING_METER_RESOURCE_NAME = "BillingMeter"
BILLING_CREDIT_GRANT_RESOURCE_NAME = "BillingCreditGrant"
BILLING_CREDIT_BALANCE_TRANSACTION_RESOURCE_NAME = "BillingCreditBalanceTransaction"
BILLING_CREDIT_BALANCE_SUMMARY_RESOURCE_NAME = "BillingCreditBalanceSummary"
ENTITLEMENTS_FEATURE_RESOURCE_NAME = "EntitlementsFeature"
ENTITLEMENTS_ACTIVE_ENTITLEMENT_RESOURCE_NAME = "EntitlementsActiveEntitlement"
INVOICE_PAYMENT_RESOURCE_NAME = "InvoicePayment"
SETUP_INTENT_RESOURCE_NAME = "SetupIntent"
SETUP_ATTEMPT_RESOURCE_NAME = "SetupAttempt"
PAYMENT_LINK_RESOURCE_NAME = "PaymentLink"
TRANSFER_RESOURCE_NAME = "Transfer"
APPLICATION_FEE_RESOURCE_NAME = "ApplicationFee"
TOPUP_RESOURCE_NAME = "Topup"
REVIEW_RESOURCE_NAME = "Review"
EARLY_FRAUD_WARNING_RESOURCE_NAME = "EarlyFraudWarning"
SHIPPING_RATE_RESOURCE_NAME = "ShippingRate"

# Vendor API version the sync pipeline pins by default. One constant so the source's version
# declaration (`StripeSource.supported_versions`) and the request layer share a single label.
STRIPE_API_VERSION_ACACIA = "2024-09-30.acacia"

# CustomerPaymentMethodHistory metadata columns. Every row is one observation of a payment
# method: either a `payment_method.*` webhook event, or a row from the initial attached-payment-
# methods sweep (a "snapshot"). The event id doubles as the row's primary key, so webhook
# redeliveries merge into the same row instead of duplicating it.
HISTORY_EVENT_ID_COLUMN = "history_event_id"
HISTORY_EVENT_TYPE_COLUMN = "history_event_type"
HISTORY_CAPTURED_AT_COLUMN = "history_captured_at"
HISTORY_PREVIOUS_ATTRIBUTES_COLUMN = "history_previous_attributes"
HISTORY_SNAPSHOT_EVENT_TYPE = "snapshot"

# `schema_mapping` key the webhook HogFunction uses to route `payment_method` events to the
# history table *in addition to* the CustomerPaymentMethod upsert routed by the bare object
# type. Stripe object types never contain ":", so this can never collide with a real one.
PAYMENT_METHOD_HISTORY_MAPPING_KEY = "payment_method:history"

# Maps PostHog resource name -> Stripe API object type (as it appears in webhook data.object.object)
#
# This is what the webhook HogFunction routes on: it reads `data.object.object` off the incoming
# event and looks the value up here to find the table to write into. A resource missing from this
# map can never be fed by a webhook, no matter how many events the endpoint subscribes to.
#
# A resource belongs here only when Stripe actually emits an event carrying that object type. The
# ones that do not are listed at the bottom of RESOURCE_TO_STRIPE_WEBHOOK_EVENT below.
#
# CustomerPaymentMethodHistory is deliberately absent: one object type key can route to only one
# schema, and "payment_method" already routes to CustomerPaymentMethod. The history table receives
# the same events through the PAYMENT_METHOD_HISTORY_MAPPING_KEY fan-out in the webhook template
# (see `StripeSource.webhook_mapping_key`).
RESOURCE_TO_STRIPE_OBJECT_TYPE: dict[str, str] = {
    ACCOUNT_RESOURCE_NAME: "account",
    BALANCE_TRANSACTION_RESOURCE_NAME: "balance_transaction",
    CHARGE_RESOURCE_NAME: "charge",
    CUSTOMER_RESOURCE_NAME: "customer",
    DISPUTE_RESOURCE_NAME: "dispute",
    INVOICE_ITEM_RESOURCE_NAME: "invoiceitem",
    INVOICE_RESOURCE_NAME: "invoice",
    PAYOUT_RESOURCE_NAME: "payout",
    PRICE_RESOURCE_NAME: "price",
    PRODUCT_RESOURCE_NAME: "product",
    REFUND_RESOURCE_NAME: "refund",
    SUBSCRIPTION_RESOURCE_NAME: "subscription",
    CREDIT_NOTE_RESOURCE_NAME: "credit_note",
    CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME: "customer_balance_transaction",
    CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME: "payment_method",
    COUPON_RESOURCE_NAME: "coupon",
    DISCOUNT_RESOURCE_NAME: "discount",
    PAYMENT_INTENT_RESOURCE_NAME: "payment_intent",
    CHECKOUT_SESSION_RESOURCE_NAME: "checkout.session",
    SUBSCRIPTION_SCHEDULE_RESOURCE_NAME: "subscription_schedule",
    PROMOTION_CODE_RESOURCE_NAME: "promotion_code",
    PLAN_RESOURCE_NAME: "plan",
    TAX_RATE_RESOURCE_NAME: "tax_rate",
    # Stripe namespaces the event as `customer.tax_id.*` but puts a bare `tax_id` object on it, so
    # this map and RESOURCE_TO_STRIPE_WEBHOOK_EVENT deliberately disagree for this one resource.
    TAX_ID_RESOURCE_NAME: "tax_id",
    QUOTE_RESOURCE_NAME: "quote",
    BILLING_METER_RESOURCE_NAME: "billing.meter",
    BILLING_CREDIT_GRANT_RESOURCE_NAME: "billing.credit_grant",
    BILLING_CREDIT_BALANCE_TRANSACTION_RESOURCE_NAME: "billing.credit_balance_transaction",
    INVOICE_PAYMENT_RESOURCE_NAME: "invoice_payment",
    SETUP_INTENT_RESOURCE_NAME: "setup_intent",
    PAYMENT_LINK_RESOURCE_NAME: "payment_link",
    TRANSFER_RESOURCE_NAME: "transfer",
    APPLICATION_FEE_RESOURCE_NAME: "application_fee",
    TOPUP_RESOURCE_NAME: "topup",
    REVIEW_RESOURCE_NAME: "review",
    EARLY_FRAUD_WARNING_RESOURCE_NAME: "radar.early_fraud_warning",
}

RESOURCE_TO_STRIPE_WEBHOOK_EVENT: dict[str, str] = {
    ACCOUNT_RESOURCE_NAME: "account",
    BALANCE_TRANSACTION_RESOURCE_NAME: "transfer",
    CHARGE_RESOURCE_NAME: "charge",
    CUSTOMER_RESOURCE_NAME: "customer",
    DISPUTE_RESOURCE_NAME: "dispute",
    INVOICE_ITEM_RESOURCE_NAME: "invoiceitem",
    INVOICE_RESOURCE_NAME: "invoice",
    PAYOUT_RESOURCE_NAME: "payout",
    PRICE_RESOURCE_NAME: "price",
    PRODUCT_RESOURCE_NAME: "product",
    REFUND_RESOURCE_NAME: "refund",
    SUBSCRIPTION_RESOURCE_NAME: "customer.subscription",
    CREDIT_NOTE_RESOURCE_NAME: "credit_note",
    # CustomerBalanceTransaction (the legacy customer credit-balance ledger returned by
    # `customers.balance_transactions.list`) has no Stripe webhook event — no event ever carries a
    # `customer_balance_transaction` object. The previous "billing" prefix only subscribed the source
    # webhook to unrelated `billing.*` events (credit grants, meters, alerts, and the distinct
    # `billing.credit_balance_transaction` object), none of which can populate this table. So it's
    # intentionally absent here and stays API-sweep-only.
    CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME: "payment_method",
    # Same event family as CustomerPaymentMethod (the values here are collapsed to a set when
    # building the Stripe subscription, so this adds no new subscribed events). What differs is
    # the write: CustomerPaymentMethod upserts the latest state per payment method, while the
    # history table appends one row per event so `payment_method.detached` (Stripe's closest
    # analogue to deletion — no `payment_method.deleted` event exists) is preserved.
    CUSTOMER_PAYMENT_METHOD_HISTORY_RESOURCE_NAME: "payment_method",
    COUPON_RESOURCE_NAME: "coupon",
    DISCOUNT_RESOURCE_NAME: "customer.discount",
    PAYMENT_INTENT_RESOURCE_NAME: "payment_intent",
    CHECKOUT_SESSION_RESOURCE_NAME: "checkout.session",
    SUBSCRIPTION_SCHEDULE_RESOURCE_NAME: "subscription_schedule",
    PROMOTION_CODE_RESOURCE_NAME: "promotion_code",
    PLAN_RESOURCE_NAME: "plan",
    TAX_RATE_RESOURCE_NAME: "tax_rate",
    # `customer.tax_id.*` events were already arriving via the CUSTOMER "customer" prefix; they
    # simply had nowhere to route until TaxId joined RESOURCE_TO_STRIPE_OBJECT_TYPE. Naming the
    # narrower prefix here is what makes the schema advertise `supports_webhooks` in the picker.
    TAX_ID_RESOURCE_NAME: "customer.tax_id",
    QUOTE_RESOURCE_NAME: "quote",
    BILLING_METER_RESOURCE_NAME: "billing.meter",
    BILLING_CREDIT_GRANT_RESOURCE_NAME: "billing.credit_grant",
    BILLING_CREDIT_BALANCE_TRANSACTION_RESOURCE_NAME: "billing.credit_balance_transaction",
    INVOICE_PAYMENT_RESOURCE_NAME: "invoice_payment",
    SETUP_INTENT_RESOURCE_NAME: "setup_intent",
    PAYMENT_LINK_RESOURCE_NAME: "payment_link",
    # Duplicates the "transfer" prefix BalanceTransaction already carries. Harmless: this map's
    # values are collapsed to a set to build the subscription, and the two tables stay distinct
    # because routing keys off the object type (`balance_transaction` vs `transfer`), not the event.
    TRANSFER_RESOURCE_NAME: "transfer",
    APPLICATION_FEE_RESOURCE_NAME: "application_fee",
    TOPUP_RESOURCE_NAME: "topup",
    REVIEW_RESOURCE_NAME: "review",
    EARLY_FRAUD_WARNING_RESOURCE_NAME: "radar.early_fraud_warning",
    # Deliberately absent, because Stripe emits no event carrying these objects. Verified against
    # the `enabled_events` literal in the pinned SDK, which is the same list `_all_known_webhook_events`
    # filters. They stay API-sweep-only:
    #   SubscriptionItem     - changes ride along on `customer.subscription.*` as nested `items`
    #   SetupAttempt         - no `setup_attempt.*` events exist
    #   ShippingRate         - no `shipping_rate.*` events exist
    #   Event                - the event log itself; subscribing to it to populate it is circular
    #   BillingCreditBalanceSummary   - only reachable as a retrieve off a credit grant
    #   EntitlementsFeature           - no `entitlements.feature.*` events exist
    #   EntitlementsActiveEntitlement - the one entitlements event carries an
    #       `entitlements.active_entitlement_summary` object (a per-customer summary), not an
    #       individual active entitlement, so routing it here would write the wrong shape.
}
