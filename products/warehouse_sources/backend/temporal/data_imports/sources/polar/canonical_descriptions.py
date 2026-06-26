"""Canonical, documentation-sourced descriptions for Polar endpoints and columns.

Sourced from the official Polar API reference (https://docs.polar.sh/api-reference). Keyed by the
resource names in `constants.py` / `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Polar table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.polar.constants import (
    BENEFIT_RESOURCE_NAME,
    CHECKOUT_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    ORDER_RESOURCE_NAME,
    ORGANIZATION_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    REFUND_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
)

# Fields shared by most Polar objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "created_at": "Time at which the object was created.",
    "modified_at": "Time at which the object was last modified, if ever.",
    "metadata": "Set of key-value pairs you can attach to the object for your own bookkeeping.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    CUSTOMER_RESOURCE_NAME: {
        "description": "A customer of an organization who can purchase products and hold subscriptions.",
        "docs_url": "https://docs.polar.sh/api-reference/customers/list",
        "columns": _columns(
            email="The customer's email address.",
            email_verified="Whether the customer's email address has been verified.",
            name="The customer's name.",
            type="Whether the customer is an individual or a team.",
            billing_name="Name shown on the customer's invoices, falling back to the customer name when unset.",
            organization_id="ID of the organization the customer belongs to.",
            billing_address="The customer's billing address.",
            tax_id="The customer's tax identifier, if any.",
        ),
    },
    PRODUCT_RESOURCE_NAME: {
        "description": "A product that can be purchased or subscribed to in Polar.",
        "docs_url": "https://docs.polar.sh/api-reference/products/list",
        "columns": _columns(
            name="The product's name.",
            description="The product's description.",
            recurring_interval="Billing interval for recurring products (e.g. month, year), or null for one-time.",
            is_recurring="Whether the product is a subscription product.",
            trial_interval_count="Number of trial interval units before billing starts, or null if there is no trial.",
            is_archived="Whether the product has been archived.",
            organization_id="ID of the organization that owns the product.",
            prices="The list of prices configured for the product.",
            benefits="The list of benefits granted by the product.",
        ),
    },
    ORDER_RESOURCE_NAME: {
        "description": "A completed purchase of a product, including one-time and subscription orders.",
        "docs_url": "https://docs.polar.sh/api-reference/orders/list",
        "columns": _columns(
            status="Status of the order (e.g. paid, refunded, partially_refunded).",
            amount="Order amount before tax, in the smallest currency unit.",
            seats="Number of seats purchased, for seat-based one-time orders.",
            tax_amount="Tax charged on the order, in the smallest currency unit.",
            currency="Three-letter ISO currency code of the order.",
            billing_reason="Reason the order was created (e.g. purchase, subscription_cycle).",
            customer_id="ID of the customer who placed the order.",
            product_id="ID of the product purchased.",
            subscription_id="ID of the subscription this order belongs to, if any.",
            discount_id="ID of the discount applied to the order, if any.",
        ),
    },
    SUBSCRIPTION_RESOURCE_NAME: {
        "description": "A recurring subscription of a customer to a product.",
        "docs_url": "https://docs.polar.sh/api-reference/subscriptions/list",
        "columns": _columns(
            status="Status of the subscription (e.g. active, canceled, past_due).",
            amount="Recurring amount of the subscription, in the smallest currency unit.",
            currency="Three-letter ISO currency code of the subscription.",
            recurring_interval="Billing interval of the subscription (e.g. month, year).",
            current_period_start="Start of the current billing period.",
            current_period_end="End of the current billing period.",
            cancel_at_period_end="Whether the subscription will cancel at the end of the current period.",
            started_at="Time at which the subscription started.",
            ended_at="Time at which the subscription ended, if it has ended.",
            customer_id="ID of the customer the subscription belongs to.",
            product_id="ID of the subscribed product.",
            discount_id="ID of the discount applied to the subscription, if any.",
        ),
    },
    REFUND_RESOURCE_NAME: {
        "description": "A refund issued against an order in Polar.",
        "docs_url": "https://docs.polar.sh/api-reference/refunds/list",
        "columns": _columns(
            status="Status of the refund (e.g. succeeded, pending, failed).",
            reason="Reason the refund was issued.",
            amount="Refunded amount, in the smallest currency unit.",
            tax_amount="Refunded tax, in the smallest currency unit.",
            currency="Three-letter ISO currency code of the refund.",
            order_id="ID of the order the refund applies to.",
            subscription_id="ID of the subscription the refund relates to, if any.",
            customer_id="ID of the customer who received the refund.",
            revoke_benefits="Whether benefits were revoked as part of the refund.",
        ),
    },
    CHECKOUT_RESOURCE_NAME: {
        "description": "A checkout session for purchasing a product in Polar.",
        "docs_url": "https://docs.polar.sh/api-reference/checkouts/list",
        "columns": _columns(
            status="Status of the checkout session (e.g. open, confirmed, succeeded, expired).",
            url="URL of the hosted checkout page.",
            expires_at="Time at which the checkout session expires.",
            amount="Amount to be charged, in the smallest currency unit.",
            tax_amount="Tax to be charged, in the smallest currency unit.",
            currency="Three-letter ISO currency code of the checkout.",
            customer_id="ID of the customer associated with the checkout, if any.",
            customer_email="Email address provided for the checkout.",
            product_id="ID of the product being purchased.",
            success_url="URL the customer is redirected to after a successful checkout.",
        ),
    },
    BENEFIT_RESOURCE_NAME: {
        "description": "A benefit that can be granted to customers through products in Polar.",
        "docs_url": "https://docs.polar.sh/api-reference/benefits/list",
        "columns": _columns(
            type="The type of benefit (e.g. custom, discord, github_repository, license_keys).",
            description="The benefit's description.",
            selectable="Whether the benefit can be added to or removed from products.",
            deletable="Whether the benefit can be deleted.",
            organization_id="ID of the organization that owns the benefit.",
        ),
    },
    ORGANIZATION_RESOURCE_NAME: {
        "description": "An organization on Polar that sells products and owns customers.",
        "docs_url": "https://docs.polar.sh/api-reference/organizations/list",
        "columns": _columns(
            name="The organization's name.",
            slug="The organization's URL slug.",
            avatar_url="URL of the organization's avatar image.",
            email="The organization's contact email address.",
            website="The organization's website URL.",
        ),
    },
}
