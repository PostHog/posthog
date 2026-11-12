"""Canonical, documentation-sourced descriptions for Creem endpoints and columns.

Sourced from the official Creem API reference (https://docs.creem.io/api-reference/introduction) and its
OpenAPI spec. Keyed by the endpoint names in `settings.py` `ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Creem table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

_DOCS_URL = "https://docs.creem.io/api-reference/introduction"

# Fields shared by the store objects (products, customers, subscriptions and so on).
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "mode": "Environment the object belongs to: test, prod or sandbox.",
    "object": "String representing the object's type.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Products": {
        "description": "A product sold in the Creem store, either a one-time purchase or a recurring subscription.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            name="Name of the product.",
            description="Brief description of the product.",
            image_url="URL of the product's cover image.",
            features="Features of the product.",
            usage_prices="Metered charges billed on top of the base price, one per meter.",
            price="Price of the product, in cents (1000 = $10.00).",
            currency="Three-letter ISO currency code, in uppercase.",
            billing_type="Billing method: recurring or onetime.",
            billing_period="Billing period, such as every-month, every-year or once.",
            recurring_interval="Unit of the recurring billing interval: day, week, month or year.",
            recurring_interval_count="Number of recurring_interval units per billing cycle. Null for one-time products.",
            trial_period_days="Length of the trial period in days. Null when the product has no trial.",
            trial_price="Amount charged at checkout to start the trial, in cents.",
            status="Lifecycle status of the product: active or archived.",
            tax_mode="Whether tax is included in the price (inclusive) or added on top of it (exclusive).",
            tax_category="Tax category of the product: saas, digital-goods-service or ebooks.",
            product_url="Product page that customers can use for express checkout.",
            default_success_url="URL the customer is redirected to after a successful payment.",
            custom_fields="Custom fields collected from the customer during checkout.",
            created_at="Time at which the product was created.",
            updated_at="Time at which the product was last updated.",
        ),
    },
    "Customers": {
        "description": "A customer who bought from the Creem store.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            email="Customer's email address.",
            name="Customer's name.",
            metadata="Additional metadata associated with the customer.",
            country="ISO 3166-1 alpha-2 country code of the customer.",
            external_id="Your own identifier for the customer, when you set one.",
            created_at="Time at which the customer was created.",
            updated_at="Time at which the customer was last updated.",
        ),
    },
    "Subscriptions": {
        "description": "A customer's recurring subscription to a product.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            product="Product the subscription is for, as an object or an identifier.",
            customer="Customer who owns the subscription, as an object or an identifier.",
            items="Items of the subscription, such as the product and its seat count.",
            collection_method="How payments for the subscription are collected.",
            status="Current status: active, canceled, unpaid, paused, trialing, scheduled_cancel or past_due.",
            last_transaction_id="Identifier of the last paid transaction.",
            last_transaction="Last paid transaction.",
            last_transaction_date="Time of the last paid transaction.",
            next_transaction_date="Time at which the next subscription payment will be charged.",
            current_period_start_date="Start of the current subscription period.",
            current_period_end_date="End of the current subscription period.",
            canceled_at="Time at which the subscription was canceled, if it was.",
            discount="Discount applied to the subscription, if any.",
            metadata="Key-value metadata of the subscription.",
            created_at="Time at which the subscription was created.",
            updated_at="Time at which the subscription was last updated.",
        ),
    },
    "Transactions": {
        "description": "A payment for a one-time purchase or an invoice for a subscription period.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            amount="Transaction amount, in cents (1000 = $10.00).",
            amount_paid="Amount the customer paid, in cents.",
            discount_amount="Discount amount, in cents.",
            currency="Three-letter ISO currency code, in uppercase.",
            type="Type of transaction: payment (one-time payment) or invoice (subscription).",
            tax_country="ISO alpha-2 country code where the tax is collected.",
            tax_amount="Sales tax amount, in cents.",
            status="Status: pending, paid, refunded, partialRefund, chargedBack, uncollectible, declined, canceled or void.",
            refunded_amount="Amount refunded, in cents.",
            order="Identifier of the order of the transaction.",
            subscription="Identifier of the subscription of the transaction.",
            customer="Identifier of the customer of the transaction.",
            description="Description of the transaction.",
            period_start="Start of the invoiced period, as a timestamp.",
            period_end="End of the invoiced period, as a timestamp.",
            created_at="Time at which the transaction was created, as a timestamp.",
        ),
    },
    "Discounts": {
        "description": "A discount code that customers can redeem at checkout.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            status="Status of the discount.",
            name="Name of the discount.",
            code="Discount code that the customer enters.",
            type="Type of the discount: percentage or fixed.",
            amount="Amount of the discount, as a percentage or a fixed amount.",
            currency="Currency of a fixed discount.",
            percentage="Percentage of a percentage discount.",
            expiry_date="Time at which the discount expires.",
            max_redemptions="Maximum number of redemptions allowed.",
            duration="How long the discount applies to a subscription.",
            duration_in_months="Number of months a repeating discount applies to a subscription.",
            applies_to_products="Identifiers of the products the discount applies to.",
            redeem_count="Number of times the discount was redeemed.",
        ),
    },
    "Licenses": {
        "description": "A license key issued to a customer for a product, with its activated instances.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            customer_id="Identifier of the customer who owns the license.",
            product_id="Identifier of the product the license belongs to.",
            status="Status of the license key: inactive, active, expired or disabled.",
            key="The license key.",
            activation="Number of instances the license key is activated on.",
            activation_limit="Maximum number of activations. Null when activations are unlimited.",
            expires_at="Time at which the license key expires. Null when it does not expire.",
            instance="Instances the license key is activated on.",
            created_at="Time at which the license key was created.",
        ),
    },
    "Affiliates": {
        "description": "An affiliate who joined the store's affiliate program.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            email="Email address the affiliate was invited with.",
            name="Display name of the affiliate, if set.",
            status="Membership status: active, pending, rejected, suspended or inactive.",
            referral_code="Affiliate's unique referral code.",
            referral_link="Affiliate's referral link. Traffic through it is attributed to the affiliate.",
            clicks="Total number of clicks on the affiliate's links.",
            conversions="Total number of conversions attributed to the affiliate.",
            earnings="Lifetime commission earned, in cents, in the affiliate's primary currency.",
            currency="Three-letter ISO currency code of the earnings amount.",
        ),
    },
    "AffiliateInvites": {
        "description": "An invitation to join the store's affiliate program.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            email="Email address the affiliate was invited with.",
            name="Display name the affiliate was invited with.",
            status="Status of the invitation: pending or accepted.",
            created_at="Time at which the invitation was created, as a timestamp.",
        ),
    },
    "Splits": {
        "description": "A revenue split that shares the payments of the store or of one product with other recipients.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            store_id="Identifier of the store that owns the split.",
            description="Description of the split.",
            type="What the split applies to: store (every payment) or product (payments for one product).",
            type_reference="Identifier of the store or the product the split applies to.",
            enabled="Whether the split is active.",
            recipients="Recipients of the split and their shares.",
            created_at="Time at which the split was created, as a Unix timestamp in milliseconds.",
        ),
    },
    "Meters": {
        "description": "A meter that aggregates usage events into billable units for usage-based pricing.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the meter.",
            "store_id": "Identifier of the store.",
            "name": "Name of the meter.",
            "event_name": "Name of the usage events the meter consumes.",
            "aggregation": "Aggregation applied to the matching events.",
            "aggregation_property": "Event property the aggregation reduces. Null for a count.",
            "filter": "Filter on the events the meter consumes. Empty clauses match all events.",
            "unit_label": "Display unit of the meter.",
            "status": "Whether the meter is active or archived.",
            "created_at": "Time at which the meter was created.",
            "updated_at": "Time at which the meter was last updated.",
        },
    },
    "UsageEvents": {
        "description": "A usage event sent to Creem for a customer. Meters aggregate these events for usage-based billing.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the usage event.",
            "customer_id": "Identifier of the customer the usage belongs to.",
            "event_id": "Your idempotency key for the event.",
            "name": "Name of the event.",
            "properties": "Attributes of the event that meter filters and aggregations read.",
            "timestamp": "Time at which the usage occurred, on the sender's clock.",
            "created_at": "Time at which Creem ingested the event.",
            "matched_meters": "Identifiers of the active meters that consume this event name, computed when read.",
        },
    },
    "CreditAccounts": {
        "description": "A customer credits account that holds a balance of prepaid credits.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the credits account.",
            "store_id": "Identifier of the store.",
            "customer_id": "Identifier of the customer who owns the account.",
            "name": "Name of the account.",
            "unit_label": "Unit label of the credits.",
            "status": "Status of the account.",
            "created_at": "Time at which the account was created.",
            "updated_at": "Time at which the account was last updated.",
        },
    },
}
