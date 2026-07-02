"""Canonical, documentation-sourced descriptions for commercetools endpoints and columns.

Sourced from the official commercetools Composable Commerce HTTP API reference
(https://docs.commercetools.com/api). Keyed by the endpoint names in `settings.py`
`COMMERCETOOLS_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
commercetools table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most commercetools resources; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the resource.",
    "version": "Current version of the resource, incremented on every update.",
    "createdAt": "Date and time the resource was created.",
    "lastModifiedAt": "Date and time the resource was last modified.",
    "key": "User-defined unique identifier for the resource.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "orders": {
        "description": "A confirmed checkout of a cart, representing a purchase made by a customer.",
        "docs_url": "https://docs.commercetools.com/api/projects/orders",
        "columns": _columns(
            orderNumber="Human-readable identifier of the order, unique within the project.",
            customerId="ID of the customer the order belongs to.",
            customerEmail="Email address of the customer who placed the order.",
            orderState="State of the order (Open, Confirmed, Complete, Cancelled).",
            paymentState="Payment state of the order (BalanceDue, Failed, Pending, CreditOwed, Paid).",
            shipmentState="Shipment state of the order (Shipped, Ready, Pending, Delayed, Partial, Backorder).",
            totalPrice="Total price of the order, after discounts and before/after tax depending on settings.",
            taxedPrice="Tax-inclusive and tax breakdown for the order.",
            lineItems="Products purchased in the order, each referencing a product and variant.",
            country="Two-letter country code for the order's shipping/tax context.",
            completedAt="Date and time the order was completed.",
        ),
    },
    "customers": {
        "description": "A registered customer account in the commercetools project.",
        "docs_url": "https://docs.commercetools.com/api/projects/customers",
        "columns": _columns(
            customerNumber="Human-readable identifier of the customer, unique within the project.",
            email="Email address of the customer.",
            firstName="Customer's first name.",
            lastName="Customer's last name.",
            companyName="Company name associated with the customer.",
            isEmailVerified="Whether the customer's email address has been verified.",
            customerGroup="Reference to the customer group the customer belongs to.",
            addresses="List of addresses stored for the customer.",
            defaultShippingAddressId="ID of the customer's default shipping address.",
            defaultBillingAddressId="ID of the customer's default billing address.",
        ),
    },
    "payments": {
        "description": "A payment representing money received or refunded for an order.",
        "docs_url": "https://docs.commercetools.com/api/projects/payments",
        "columns": _columns(
            customer="Reference to the customer the payment belongs to.",
            amountPlanned="Amount that the platform expects to receive or refund.",
            paymentMethodInfo="Information about the payment method used.",
            paymentStatus="Current status of the payment, including interface and state.",
            transactions="List of financial transactions (Authorization, Charge, Refund, etc.).",
            interfaceId="Identifier used by the payment service provider for this payment.",
        ),
    },
    "carts": {
        "description": "A shopping cart holding line items a customer intends to purchase.",
        "docs_url": "https://docs.commercetools.com/api/projects/carts",
        "columns": _columns(
            customerId="ID of the customer the cart belongs to, if any.",
            customerEmail="Email address associated with the cart.",
            cartState="State of the cart (Active, Merged, Ordered, Frozen).",
            totalPrice="Total price of the cart's line items after discounts.",
            taxedPrice="Tax-inclusive and tax breakdown for the cart.",
            lineItems="Products added to the cart, each referencing a product and variant.",
            country="Two-letter country code for the cart's pricing/tax context.",
            anonymousId="Identifier for an anonymous session owning the cart.",
        ),
    },
    "product_projections": {
        "description": "A projected (current or staged) view of a product, ready for storefront display.",
        "docs_url": "https://docs.commercetools.com/api/projects/productProjections",
        "columns": _columns(
            name="Localized name of the product.",
            description="Localized description of the product.",
            slug="Localized, URL-friendly identifier of the product.",
            productType="Reference to the product type defining the product's attributes.",
            categories="References to the categories the product is assigned to.",
            masterVariant="The product's master (default) variant, including SKU and prices.",
            variants="Additional variants of the product.",
            published="Whether the product is currently published.",
        ),
    },
    "categories": {
        "description": "A category used to organize products into a navigable hierarchy.",
        "docs_url": "https://docs.commercetools.com/api/projects/categories",
        "columns": _columns(
            name="Localized name of the category.",
            slug="Localized, URL-friendly identifier of the category.",
            description="Localized description of the category.",
            parent="Reference to the parent category, if this is a subcategory.",
            ancestors="References to all ancestor categories up the hierarchy.",
            orderHint="Decimal string controlling the category's order among siblings.",
        ),
    },
    "discount_codes": {
        "description": "A discount code customers can redeem to apply a cart discount.",
        "docs_url": "https://docs.commercetools.com/api/projects/discountCodes",
        "columns": _columns(
            code="The unique code customers enter to apply the discount.",
            name="Localized name of the discount code.",
            description="Localized description of the discount code.",
            cartDiscounts="References to the cart discounts applied by this code.",
            isActive="Whether the discount code is currently active.",
            maxApplications="Maximum number of times the code can be applied overall.",
            maxApplicationsPerCustomer="Maximum number of times one customer can apply the code.",
        ),
    },
    "inventory": {
        "description": "An inventory entry tracking stock quantity for a SKU at a supply channel.",
        "docs_url": "https://docs.commercetools.com/api/projects/inventory",
        "columns": _columns(
            sku="SKU of the product variant this inventory entry tracks.",
            supplyChannel="Reference to the supply channel the stock is held at, if any.",
            quantityOnStock="Total quantity of items currently on stock.",
            availableQuantity="Quantity available for sale (on stock minus reserved).",
            restockableInDays="Number of days until the item can be restocked.",
            expectedDelivery="Date and time when restocked items are expected to arrive.",
        ),
    },
}
