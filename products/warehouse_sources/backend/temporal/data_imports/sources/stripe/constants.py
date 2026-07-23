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
COUPON_RESOURCE_NAME = "Coupon"
DISCOUNT_RESOURCE_NAME = "Discount"

# Vendor API version labels — opaque Stripe date-versions, never parsed or ordered.
# One set of constants so the source's version declaration (`StripeSource.supported_versions`),
# the request layer, and the version picker all share the same labels.
STRIPE_API_VERSION_ACACIA = "2024-09-30.acacia"  # legacy default before selectable versions
STRIPE_VERSION_ACACIA_2025 = "2025-02-24.acacia"
STRIPE_VERSION_BASIL = "2025-08-27.basil"
STRIPE_VERSION_CLOVER = "2026-02-25.clover"

LEGACY_STRIPE_API_VERSION = STRIPE_API_VERSION_ACACIA
# New sources default to the newest version whose canonical column hints are still valid, so
# Revenue analytics keeps working out of the box. basil/clover are opt-in until the canonical
# schema/descriptions are version-aware (they reshape invoice.subscription, price.product, etc.).
DEFAULT_STRIPE_API_VERSION = STRIPE_VERSION_ACACIA_2025

# Selectable versions shown in the source's "API version" picker, newest first. Legacy is listed so
# sources pinned to it (framework default / migration 0058) round-trip in the picker instead of
# rendering blank; new sources default to DEFAULT_STRIPE_API_VERSION, not legacy.
STRIPE_API_VERSIONS: dict[str, str] = {
    STRIPE_VERSION_CLOVER: "Clover (2026-02-25)",
    STRIPE_VERSION_BASIL: "Basil (2025-08-27)",
    STRIPE_VERSION_ACACIA_2025: "Acacia (2025-02-24)",
    LEGACY_STRIPE_API_VERSION: "Acacia (2024-09-30, legacy)",
}

# The external table definitions in external_table_definitions.py were built for these versions.
# For other versions, schema is auto-inferred from the data.
STRIPE_VERSIONS_WITH_EXTERNAL_TABLE_DEFINITIONS: set[str] = {
    LEGACY_STRIPE_API_VERSION,
    STRIPE_VERSION_ACACIA_2025,
}

# Maps PostHog resource name -> Stripe API object type (as it appears in webhook data.object.object)
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
    COUPON_RESOURCE_NAME: "coupon",
    DISCOUNT_RESOURCE_NAME: "customer.discount",
}
