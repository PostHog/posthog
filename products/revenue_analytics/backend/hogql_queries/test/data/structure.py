from posthog.schema import RevenueAnalyticsEventItem, RevenueCurrencyPropertyConfig

from posthog.warehouse.models import CLICKHOUSE_HOGQL_MAPPING


def _convert_columns(basic_types: dict[str, str]):
    return {
        str(key): {
            "hogql": CLICKHOUSE_HOGQL_MAPPING[value].__name__,
            "clickhouse": value,
            "valid": True,
        }
        for key, value in basic_types.items()
    }


REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT = RevenueAnalyticsEventItem(
    eventName="purchase",
    revenueProperty="revenue",
    productProperty="product",
    couponProperty="coupon",
    subscriptionProperty="subscription",
    subscriptionDropoffDays=45,
    subscriptionDropoffMode="last_event",
    revenueCurrencyProperty=RevenueCurrencyPropertyConfig(property="currency"),
)

STRIPE_CHARGE_COLUMNS = _convert_columns(
    {
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
)

STRIPE_CUSTOMER_COLUMNS = _convert_columns(
    {
        "id": "String",
        "created": "DateTime",
        "name": "String",
        "email": "String",
        "phone": "String",
        "address": "String",
        "metadata": "String",
    }
)

STRIPE_INVOICE_COLUMNS = _convert_columns(
    {
        "id": "String",
        "tax": "Int64",
        "paid": "UInt8",
        "lines": "String",
        "total": "Int64",
        "charge": "String",
        "issuer": "String",
        "number": "String",
        "object": "String",
        "status": "String",
        "created": "DateTime",
        "currency": "String",
        "customer": "String",
        "subscription": "String",
        "discount": "String",
        "due_date": "DateTime",
        "livemode": "UInt8",
        "metadata": "String",
        "subtotal": "Int64",
        "attempted": "UInt8",
        "discounts": "String",
        "rendering": "String",
        "amount_due": "Int64",
        "period_start_at": "DateTime",
        "period_end_at": "DateTime",
        "amount_paid": "Int64",
        "description": "String",
        "invoice_pdf": "String",
        "account_name": "String",
        "auto_advance": "UInt8",
        "effective_at": "DateTime",
        "attempt_count": "UInt8",
        "automatic_tax": "String",
        "customer_name": "String",
        "billing_reason": "String",
        "customer_email": "String",
        "ending_balance": "Int64",
        "payment_intent": "String",
        "account_country": "String",
        "amount_shipping": "Int64",
        "amount_remaining": "Int64",
        "customer_address": "String",
        "customer_tax_ids": "String",
        "paid_out_of_band": "UInt8",
        "payment_settings": "String",
        "starting_balance": "Int64",
        "collection_method": "String",
        "default_tax_rates": "String",
        "total_tax_amounts": "String",
        "hosted_invoice_url": "String",
        "status_transitions": "String",
        "customer_tax_exempt": "String",
        "total_excluding_tax": "Int64",
        "subscription_details": "String",
        "webhooks_delivered_at": "DateTime",
        "subtotal_excluding_tax": "Int64",
        "total_discount_amounts": "String",
        "pre_payment_credit_notes_amount": "Int64",
        "post_payment_credit_notes_amount": "Int64",
    }
)

STRIPE_PRODUCT_COLUMNS = _convert_columns(
    {
        "id": "String",
        "name": "String",
        "type": "String",
        "active": "UInt8",
        "images": "String",
        "object": "String",
        "created": "DateTime",
        "updated_at": "DateTime",
        "features": "String",
        "livemode": "UInt8",
        "metadata": "String",
        "tax_code": "String",
        "attributes": "String",
        "description": "String",
        "default_price_id": "String",
    }
)

STRIPE_SUBSCRIPTION_COLUMNS = _convert_columns(
    {
        "id": "String",
        "customer": "String",
        "plan": "String",
        "created": "DateTime",
        "ended_at": "DateTime",
        "status": "String",
        "metadata": "String",
    }
)
