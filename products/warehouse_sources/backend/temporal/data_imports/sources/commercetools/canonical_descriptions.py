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
    "shopping_lists": {
        "description": "A shopping list, used to model wishlists and saved carts a customer keeps before checkout.",
        "docs_url": "https://docs.commercetools.com/api/projects/shoppingLists",
        "columns": _columns(
            name="Localized name of the shopping list.",
            slug="Localized, URL-friendly identifier of the shopping list.",
            description="Localized description of the shopping list.",
            customer="Reference to the customer the shopping list belongs to.",
            anonymousId="Identifier for an anonymous session owning the shopping list.",
            lineItems="Product variants on the list, each with a quantity and the date it was added.",
            textLineItems="Free-text entries on the list that do not reference a product.",
            store="Reference to the store the shopping list belongs to.",
            businessUnit="Reference to the business unit the shopping list belongs to.",
            deleteDaysAfterLastModification="Days of inactivity after which the shopping list is deleted.",
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
    "product_types": {
        "description": "A product type defining the common custom attributes shared by many products. Products and product projections reference the product type they were created from.",
        "docs_url": "https://docs.commercetools.com/api/projects/productTypes",
        "columns": _columns(
            name="Name of the product type, unique within the project.",
            description="Description of the product type.",
            attributes="Attribute definitions of the product type, including each attribute's name, type and constraints.",
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
    "standalone_prices": {
        "description": "A price held outside the product it applies to, matched to a product variant by SKU.",
        "docs_url": "https://docs.commercetools.com/api/projects/standalone-prices",
        "columns": _columns(
            sku="SKU of the product variant the price applies to.",
            value="Money value of the price.",
            country="Two-letter country code the price applies in.",
            customerGroup="Reference to the customer group the price applies to.",
            channel="Reference to the distribution channel the price applies to.",
            validFrom="Date and time from which the price is valid.",
            validUntil="Date and time until which the price is valid.",
            tiers="Quantity-based price tiers that override the value above a threshold.",
            discounted="Discounted price set by a product discount.",
            staged="Staged changes to the price that are not yet published.",
            active="Whether the price is currently active.",
        ),
    },
    "stores": {
        "description": "A store, modelling the physical or digital context a customer shops in. Orders and carts reference the store they belong to.",
        "docs_url": "https://docs.commercetools.com/api/projects/stores",
        "columns": _columns(
            name="Localized name of the store.",
            languages="Languages configured for the store, as IETF language tags.",
            countries="Countries the store ships to or operates in.",
            distributionChannels="References to the channels the store distributes products through.",
            supplyChannels="References to the channels the store sources inventory from.",
            productSelections="Product selections that control which products the store offers.",
            storefront="Storefront configuration for the store, such as its URLs.",
        ),
    },
    "channels": {
        "description": "A channel, representing a source or destination such as a warehouse or a physical store. Inventory entries and orders reference channels as supply and distribution channels.",
        "docs_url": "https://docs.commercetools.com/api/projects/channels",
        "columns": _columns(
            name="Localized name of the channel.",
            description="Localized description of the channel.",
            roles="Roles the channel can take (InventorySupply, ProductDistribution, OrderExport, OrderImport, Primary).",
            address="Physical address of the channel.",
            geoLocation="Geographic location of the channel, as a GeoJSON point.",
            reviewRatingStatistics="Aggregated review ratings for the channel.",
        ),
    },
    "customer_groups": {
        "description": "A customer group used to segment customers, for example for group-specific prices. Customers, carts and orders reference the group they belong to.",
        "docs_url": "https://docs.commercetools.com/api/projects/customerGroups",
        "columns": _columns(
            name="Unique name of the customer group.",
        ),
    },
    "states": {
        "description": "A state in a custom state machine, used to model the lifecycle of orders, line items, products, reviews and payments.",
        "docs_url": "https://docs.commercetools.com/api/projects/states",
        "columns": _columns(
            type="Resource the state applies to (OrderState, LineItemState, ProductState, ReviewState, PaymentState, QuoteState and others).",
            name="Localized name of the state.",
            description="Localized description of the state.",
            initial="Whether the state is the initial state of its state machine.",
            builtIn="Whether the state is a built-in state that cannot be deleted.",
            roles="Roles the state carries (ReviewIncludedInStatistics, Return).",
            transitions="References to the states this state can transition to. An empty list means no transitions are allowed; absent means all are.",
        ),
    },
    "messages": {
        "description": "A change event recorded for a resource, such as OrderStateChanged or CustomerCreated. Only recorded while the Messages Query feature is enabled for the project, and only kept until the project's message retention period expires, so this table covers that window rather than all history.",
        "docs_url": "https://docs.commercetools.com/api/projects/messages",
        "columns": _columns(
            type="Type of the message, naming the change it records (for example OrderStateChanged).",
            resource="Reference to the resource the message was recorded for.",
            resourceVersion="Version of the resource at the time the message was recorded.",
            sequenceNumber="Position of the message in the ordered sequence of messages for its resource.",
            resourceUserProvidedIdentifiers="User-provided identifiers of the resource, such as its key, SKU or order number.",
        ),
    },
}
