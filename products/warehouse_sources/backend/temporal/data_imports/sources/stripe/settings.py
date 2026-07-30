"""Stripe analytics source settings and constants"""

# the most popular endpoints
# Full list of the Stripe API endpoints you can find here: https://stripe.com/docs/api.
# These endpoints are converted into ExternalDataSchema objects when a source is linked.

from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
    ACCOUNT_RESOURCE_NAME,
    APPLICATION_FEE_RESOURCE_NAME,
    BALANCE_TRANSACTION_RESOURCE_NAME,
    BILLING_CREDIT_BALANCE_SUMMARY_RESOURCE_NAME,
    BILLING_CREDIT_BALANCE_TRANSACTION_RESOURCE_NAME,
    BILLING_CREDIT_GRANT_RESOURCE_NAME,
    BILLING_METER_RESOURCE_NAME,
    CHARGE_RESOURCE_NAME,
    CHECKOUT_SESSION_RESOURCE_NAME,
    COUPON_RESOURCE_NAME,
    CREDIT_NOTE_RESOURCE_NAME,
    CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
    CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    DISCOUNT_RESOURCE_NAME,
    DISPUTE_RESOURCE_NAME,
    EARLY_FRAUD_WARNING_RESOURCE_NAME,
    ENTITLEMENTS_ACTIVE_ENTITLEMENT_RESOURCE_NAME,
    ENTITLEMENTS_FEATURE_RESOURCE_NAME,
    EVENT_RESOURCE_NAME,
    INVOICE_ITEM_RESOURCE_NAME,
    INVOICE_PAYMENT_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    PAYMENT_INTENT_RESOURCE_NAME,
    PAYMENT_LINK_RESOURCE_NAME,
    PAYOUT_RESOURCE_NAME,
    PLAN_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    PROMOTION_CODE_RESOURCE_NAME,
    QUOTE_RESOURCE_NAME,
    REFUND_RESOURCE_NAME,
    REVIEW_RESOURCE_NAME,
    SETUP_ATTEMPT_RESOURCE_NAME,
    SETUP_INTENT_RESOURCE_NAME,
    SHIPPING_RATE_RESOURCE_NAME,
    SUBSCRIPTION_ITEM_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
    SUBSCRIPTION_SCHEDULE_RESOURCE_NAME,
    TAX_ID_RESOURCE_NAME,
    TAX_RATE_RESOURCE_NAME,
    TOPUP_RESOURCE_NAME,
    TRANSFER_RESOURCE_NAME,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    BALANCE_TRANSACTION_RESOURCE_NAME,
    CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    DISPUTE_RESOURCE_NAME,
    INVOICE_ITEM_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    PAYOUT_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    REFUND_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
    CREDIT_NOTE_RESOURCE_NAME,
    CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
    CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME,
    COUPON_RESOURCE_NAME,
    DISCOUNT_RESOURCE_NAME,
    PAYMENT_INTENT_RESOURCE_NAME,
    CHECKOUT_SESSION_RESOURCE_NAME,
    SUBSCRIPTION_ITEM_RESOURCE_NAME,
    SUBSCRIPTION_SCHEDULE_RESOURCE_NAME,
    PROMOTION_CODE_RESOURCE_NAME,
    PLAN_RESOURCE_NAME,
    TAX_RATE_RESOURCE_NAME,
    TAX_ID_RESOURCE_NAME,
    QUOTE_RESOURCE_NAME,
    EVENT_RESOURCE_NAME,
    BILLING_METER_RESOURCE_NAME,
    BILLING_CREDIT_GRANT_RESOURCE_NAME,
    BILLING_CREDIT_BALANCE_TRANSACTION_RESOURCE_NAME,
    BILLING_CREDIT_BALANCE_SUMMARY_RESOURCE_NAME,
    ENTITLEMENTS_FEATURE_RESOURCE_NAME,
    ENTITLEMENTS_ACTIVE_ENTITLEMENT_RESOURCE_NAME,
    INVOICE_PAYMENT_RESOURCE_NAME,
    SETUP_INTENT_RESOURCE_NAME,
    SETUP_ATTEMPT_RESOURCE_NAME,
    PAYMENT_LINK_RESOURCE_NAME,
    TRANSFER_RESOURCE_NAME,
    APPLICATION_FEE_RESOURCE_NAME,
    TOPUP_RESOURCE_NAME,
    REVIEW_RESOURCE_NAME,
    EARLY_FRAUD_WARNING_RESOURCE_NAME,
    SHIPPING_RATE_RESOURCE_NAME,
)


# Restricted-key scope each importable endpoint needs, as `rak_` + the identifier Stripe publishes at
# https://docs.stripe.com/stripe-apps/reference/permissions. `StripeSource.PERMISSIONS` is built from
# this, and that list is what pre-fills the key-creation form we hand customers — so an endpoint added
# to `ENDPOINTS` without an entry here yields a key that can't read its table, and the sync then fails
# telling the customer to add a scope our own link never offered.
#
# `None` means the endpoint rides on another entry's scope or has no scope of its own. Watch out for
# the names that don't match the API resource: Price is `plan`, Payment Links is plural, Top-ups is
# `top_up`. Where Stripe publishes no scope at all, say so rather than guessing a name — an unknown
# token in the pre-fill URL is worse than an absent one.
ENDPOINT_REQUIRED_PERMISSIONS: dict[str, str | None] = {
    BALANCE_TRANSACTION_RESOURCE_NAME: "rak_balance_transaction_source_read",
    CHARGE_RESOURCE_NAME: "rak_charge_read",
    CUSTOMER_RESOURCE_NAME: "rak_customer_read",
    DISPUTE_RESOURCE_NAME: "rak_dispute_read",
    INVOICE_ITEM_RESOURCE_NAME: "rak_invoice_read",
    INVOICE_RESOURCE_NAME: "rak_invoice_read",
    PAYOUT_RESOURCE_NAME: "rak_payout_read",
    PRICE_RESOURCE_NAME: "rak_plan_read",
    PRODUCT_RESOURCE_NAME: "rak_product_read",
    REFUND_RESOURCE_NAME: None,  # Rides on charge_read
    SUBSCRIPTION_RESOURCE_NAME: "rak_subscription_read",
    CREDIT_NOTE_RESOURCE_NAME: "rak_credit_note_read",
    CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME: None,  # Listed off the customer
    CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME: "rak_payment_method_read",
    COUPON_RESOURCE_NAME: "rak_coupon_read",
    DISCOUNT_RESOURCE_NAME: None,  # Webhook-only, never listed over the API
    PAYMENT_INTENT_RESOURCE_NAME: "rak_payment_intent_read",
    CHECKOUT_SESSION_RESOURCE_NAME: "rak_checkout_session_read",
    SUBSCRIPTION_ITEM_RESOURCE_NAME: None,  # Rides on subscription_read
    SUBSCRIPTION_SCHEDULE_RESOURCE_NAME: None,  # Rides on subscription_read
    PROMOTION_CODE_RESOURCE_NAME: "rak_promotion_code_read",
    PLAN_RESOURCE_NAME: "rak_plan_read",
    TAX_RATE_RESOURCE_NAME: "rak_tax_rate_read",
    TAX_ID_RESOURCE_NAME: None,  # Read off the customer; Stripe publishes no tax_id scope
    QUOTE_RESOURCE_NAME: "rak_quote_read",
    EVENT_RESOURCE_NAME: "rak_event_read",
    BILLING_METER_RESOURCE_NAME: "rak_billing_meter_read",
    BILLING_CREDIT_GRANT_RESOURCE_NAME: None,  # Stripe publishes no credit-grant scope
    BILLING_CREDIT_BALANCE_TRANSACTION_RESOURCE_NAME: None,  # As above
    BILLING_CREDIT_BALANCE_SUMMARY_RESOURCE_NAME: None,  # Retrieved off a credit grant
    ENTITLEMENTS_FEATURE_RESOURCE_NAME: "rak_entitlement_read",
    ENTITLEMENTS_ACTIVE_ENTITLEMENT_RESOURCE_NAME: "rak_entitlement_read",
    INVOICE_PAYMENT_RESOURCE_NAME: "rak_invoice_read",
    SETUP_INTENT_RESOURCE_NAME: "rak_setup_intent_read",
    SETUP_ATTEMPT_RESOURCE_NAME: "rak_setup_intent_read",
    PAYMENT_LINK_RESOURCE_NAME: "rak_payment_links_read",
    TRANSFER_RESOURCE_NAME: "rak_transfer_read",
    APPLICATION_FEE_RESOURCE_NAME: "rak_application_fee_read",
    TOPUP_RESOURCE_NAME: "rak_top_up_read",
    REVIEW_RESOURCE_NAME: "rak_review_read",
    EARLY_FRAUD_WARNING_RESOURCE_NAME: None,  # Stripe publishes no early-fraud-warning scope
    SHIPPING_RATE_RESOURCE_NAME: "rak_shipping_rate_read",
}

# Scopes we need regardless of which tables are selected.
NON_ENDPOINT_PERMISSIONS = (
    "rak_connected_account_read",  # Connect account reads across the source
    "rak_webhook_write",  # Automatic webhook creation
)


INCREMENTAL_ENDPOINTS = (
    ACCOUNT_RESOURCE_NAME,
    BALANCE_TRANSACTION_RESOURCE_NAME,
    CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    DISPUTE_RESOURCE_NAME,
    INVOICE_ITEM_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    PAYOUT_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    REFUND_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
    CREDIT_NOTE_RESOURCE_NAME,
    COUPON_RESOURCE_NAME,
    PAYMENT_INTENT_RESOURCE_NAME,
    CHECKOUT_SESSION_RESOURCE_NAME,
    SUBSCRIPTION_SCHEDULE_RESOURCE_NAME,
    PROMOTION_CODE_RESOURCE_NAME,
    PLAN_RESOURCE_NAME,
    TAX_RATE_RESOURCE_NAME,
    EVENT_RESOURCE_NAME,
    INVOICE_PAYMENT_RESOURCE_NAME,
    SETUP_INTENT_RESOURCE_NAME,
    TRANSFER_RESOURCE_NAME,
    APPLICATION_FEE_RESOURCE_NAME,
    TOPUP_RESOURCE_NAME,
    REVIEW_RESOURCE_NAME,
    EARLY_FRAUD_WARNING_RESOURCE_NAME,
    SHIPPING_RATE_RESOURCE_NAME,
)

# Endpoints that have no API list path — populated only via webhooks.
WEBHOOK_ONLY_ENDPOINTS = (DISCOUNT_RESOURCE_NAME,)

# Stripe objects that carry no timestamp at all, so there is nothing stable to partition on.
# `stripe_source` leaves partitioning off for these instead of falling back to `created`, which the
# Delta partitioner would KeyError on.
NON_PARTITIONED_ENDPOINTS = (
    ENTITLEMENTS_FEATURE_RESOURCE_NAME,
    ENTITLEMENTS_ACTIVE_ENTITLEMENT_RESOURCE_NAME,
    PAYMENT_LINK_RESOURCE_NAME,
    BILLING_CREDIT_BALANCE_SUMMARY_RESOURCE_NAME,
)

# Endpoints keyed by something other than `id`. Stripe's credit balance summary is a per-customer
# view rather than a stored object, so it has no id of its own — the credit grant it was fetched for
# is what makes each row unique.
PRIMARY_KEYS: dict[str, list[str]] = {
    BILLING_CREDIT_BALANCE_SUMMARY_RESOURCE_NAME: ["credit_grant"],
}
DEFAULT_PRIMARY_KEYS = ["id"]

APPEND_ONLY_INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    ACCOUNT_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    BALANCE_TRANSACTION_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    SUBSCRIPTION_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    CUSTOMER_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    PRODUCT_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    PRICE_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    INVOICE_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    CHARGE_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    DISPUTE_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    INVOICE_ITEM_RESOURCE_NAME: [
        {
            "label": "date",
            "type": IncrementalFieldType.DateTime,
            "field": "date",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    PAYOUT_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    REFUND_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    CREDIT_NOTE_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    COUPON_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    # Discount objects expose `start`/`end`, not `created`. Without this entry the partition key
    # falls back to "created" (stripe_source), which Discount rows lack, so a KeyError kills the
    # sync as soon as real customer.discount.* webhook events arrive.
    DISCOUNT_RESOURCE_NAME: [
        {
            "label": "start",
            "type": IncrementalFieldType.DateTime,
            "field": "start",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    **{
        # Every one of these list endpoints accepts the server-side `created` range filter
        # (`created[gt]` / `created[lt]`), which is what `get_rows` sends for an append sync, and
        # every object carries a `created` Unix timestamp. Endpoints whose list path has no
        # `created` filter (e.g. Quote, TaxId, the billing.* resources) stay full refresh and simply
        # partition on the object's own `created` via the fallback in `stripe_source`.
        endpoint: [
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.Integer,
            }
        ]
        for endpoint in (
            PAYMENT_INTENT_RESOURCE_NAME,
            CHECKOUT_SESSION_RESOURCE_NAME,
            SUBSCRIPTION_SCHEDULE_RESOURCE_NAME,
            PROMOTION_CODE_RESOURCE_NAME,
            PLAN_RESOURCE_NAME,
            TAX_RATE_RESOURCE_NAME,
            EVENT_RESOURCE_NAME,
            INVOICE_PAYMENT_RESOURCE_NAME,
            SETUP_INTENT_RESOURCE_NAME,
            TRANSFER_RESOURCE_NAME,
            APPLICATION_FEE_RESOURCE_NAME,
            TOPUP_RESOURCE_NAME,
            REVIEW_RESOURCE_NAME,
            EARLY_FRAUD_WARNING_RESOURCE_NAME,
            SHIPPING_RATE_RESOURCE_NAME,
        )
    },
}
