from posthog.schema import CurrencyCode, RevenueTrackingConfig

REVENUE_TRACKING_CONFIG = RevenueTrackingConfig(baseCurrency=CurrencyCode.GBP, events=[])

STRIPE_CHARGE_COLUMNS = {
    "id": "String",
    "paid": "Int8",
    "amount": "Int64",
    "object": "String",
    "status": "String",
    "created": "DateTime",
    "invoice": "String",
    "captured": "Int8",
    "currency": "String",
    "customer": "String",
    "disputed": "Int8",
    "livemode": "Int8",
    "metadata": "String",
    "refunded": "Int8",
    "description": "String",
    "receipt_url": "String",
    "failure_code": "String",
    "fraud_details": "String",
    "radar_options": "String",
    "receipt_email": "String",
    "payment_intent": "String",
    "payment_method": "String",
    "amount_captured": "Int64",
    "amount_refunded": "Int64",
    "billing_details": "String",
    "failure_message": "String",
    "balance_transaction": "String",
    "statement_descriptor": "String",
    "calculated_statement_descriptor": "String",
    "source": "String",
    "outcome": "String",
    "payment_method_details": "String",
}

STRIPE_CUSTOMER_COLUMNS = {
    "id": "String",
    "created": "DateTime",
    "name": "String",
    "email": "String",
    "phone": "String",
}
