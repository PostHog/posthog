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

# Vendor API version the sync pipeline pins by default. One constant so the source's version
# declaration (`StripeSource.supported_versions`) and the request layer share a single label.
STRIPE_API_VERSION_ACACIA = "2024-09-30.acacia"

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
