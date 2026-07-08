"""Canonical, documentation-sourced descriptions for Paddle endpoints and columns.

Sourced from the official Paddle Billing API reference (https://developer.paddle.com/api-reference).
Keyed by the resource names in `constants.py` (used by `settings.py` `ENDPOINTS`), which match the
`ExternalDataSchema.name` of a synced Paddle table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.constants import (
    ADJUSTMENT_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    DISCOUNT_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
    TRANSACTION_RESOURCE_NAME,
)

# Fields shared by most Paddle Billing entities; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique Paddle identifier for the object (prefixed by type, e.g. txn_, sub_).",
    "status": "Current status of the object.",
    "created_at": "Time at which the object was created (RFC 3339).",
    "updated_at": "Time at which the object was last updated (RFC 3339).",
    "custom_data": "Set of custom key-value data attached to the object.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    CUSTOMER_RESOURCE_NAME: {
        "description": "A customer who can hold subscriptions and be billed in Paddle.",
        "docs_url": "https://developer.paddle.com/api-reference/customers/overview",
        "columns": _columns(
            email="Customer's email address.",
            name="Customer's full name.",
            locale="Customer's preferred locale (IETF BCP 47 language tag).",
            marketing_consent="Whether the customer has opted in to marketing communications.",
        ),
    },
    DISCOUNT_RESOURCE_NAME: {
        "description": "A discount (coupon) that reduces the amount charged on transactions or subscriptions.",
        "docs_url": "https://developer.paddle.com/api-reference/discounts/overview",
        "columns": _columns(
            description="Internal description of the discount.",
            type="Type of discount: flat, flat_per_seat, or percentage.",
            amount="Amount of the discount (a percentage or a monetary amount, depending on type).",
            currency_code="Three-letter ISO currency code for flat discounts.",
            code="Code customers can enter at checkout to apply the discount, if any.",
            enabled_for_checkout="Whether the discount can be applied at checkout.",
            recur="Whether the discount applies to recurring billing periods.",
            maximum_recurring_intervals="Number of billing periods the recurring discount applies for.",
            usage_limit="Maximum number of times the discount can be redeemed.",
            times_used="Number of times the discount has been redeemed.",
            expires_at="Time at which the discount expires (RFC 3339), if set.",
        ),
    },
    PRICE_RESOURCE_NAME: {
        "description": "A price for a product, including amount, billing cycle, and trial settings.",
        "docs_url": "https://developer.paddle.com/api-reference/prices/overview",
        "columns": _columns(
            product_id="ID of the product this price belongs to.",
            description="Internal description of the price.",
            name="Name of the price, shown to customers.",
            type="Whether the price is standard or custom.",
            billing_cycle="Billing cycle (interval and frequency) for recurring prices; null for one-time.",
            trial_period="Trial period (interval and frequency) offered before billing starts, if any.",
            tax_mode="How tax is calculated for the price (account_setting, external, or internal).",
            unit_price="Base unit price (amount and currency_code) for the price.",
            quantity="Allowed minimum and maximum quantity for the price.",
        ),
    },
    PRODUCT_RESOURCE_NAME: {
        "description": "A product or service you sell, which prices are attached to.",
        "docs_url": "https://developer.paddle.com/api-reference/products/overview",
        "columns": _columns(
            name="The product's name.",
            description="Description of the product.",
            type="Whether the product is standard or custom.",
            tax_category="Tax category that determines the tax rate applied (e.g. standard, saas, ebook).",
            image_url="URL of the product's image.",
        ),
    },
    SUBSCRIPTION_RESOURCE_NAME: {
        "description": "A customer's recurring billing arrangement against one or more prices.",
        "docs_url": "https://developer.paddle.com/api-reference/subscriptions/overview",
        "columns": _columns(
            customer_id="ID of the customer who owns the subscription.",
            address_id="ID of the customer address used for the subscription.",
            business_id="ID of the customer business associated with the subscription, if any.",
            currency_code="Three-letter ISO currency code the subscription bills in.",
            collection_mode="How the subscription is collected: automatic or manual.",
            started_at="Time at which the subscription started (RFC 3339).",
            first_billed_at="Time at which the subscription was first billed (RFC 3339).",
            next_billed_at="Time at which the subscription will next bill (RFC 3339).",
            paused_at="Time at which the subscription was paused (RFC 3339), if applicable.",
            canceled_at="Time at which the subscription was canceled (RFC 3339), if applicable.",
            current_billing_period="Start and end of the current billing period.",
            billing_cycle="Billing cycle (interval and frequency) of the subscription.",
            items="Line items (prices and quantities) included in the subscription.",
        ),
    },
    TRANSACTION_RESOURCE_NAME: {
        "description": "A financial transaction — a payment, refund, or credit — for a customer.",
        "docs_url": "https://developer.paddle.com/api-reference/transactions/overview",
        "columns": _columns(
            customer_id="ID of the customer the transaction is for.",
            subscription_id="ID of the subscription the transaction relates to, if any.",
            invoice_id="ID of the invoice generated for the transaction, if any.",
            invoice_number="Human-readable invoice number for the transaction, if any.",
            origin="What triggered the transaction (e.g. web, subscription_recurring, api).",
            currency_code="Three-letter ISO currency code of the transaction.",
            collection_mode="How the transaction is collected: automatic or manual.",
            billed_at="Time at which the transaction was billed (RFC 3339); the incremental cursor.",
            details="Calculated totals and tax breakdown for the transaction.",
            items="Line items (prices and quantities) included in the transaction.",
            payments="Payment attempts made against the transaction.",
        ),
    },
    ADJUSTMENT_RESOURCE_NAME: {
        "description": "A refund or credit applied to a transaction, reducing or returning charged amounts.",
        "docs_url": "https://developer.paddle.com/api-reference/adjustments/overview",
        "columns": _columns(
            action="Type of adjustment: refund, credit, chargeback, chargeback_reverse, or chargeback_warning.",
            type="Scope of the adjustment: full for the transaction grand total or partial for specific line items.",
            transaction_id="ID of the transaction the adjustment is against.",
            subscription_id="ID of the subscription related to the adjustment, if any.",
            customer_id="ID of the customer the adjustment is for.",
            reason="Reason given for the adjustment.",
            currency_code="Three-letter ISO currency code of the adjustment.",
            items="Line items the adjustment applies to.",
            totals="Calculated totals (subtotal, tax, total) for the adjustment.",
            payout_totals="Adjustment totals in your payout currency.",
        ),
    },
}
