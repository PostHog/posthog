import json

from .fragments import (
    COUNT_FRAGMENT,
    CUSTOMER_FRAGMENT,
    ID_NAME_CREATED_UPDATED_FRAGMENT,
    ID_NAME_FRAGMENT,
    KV_FRAGMENT,
    LINE_ITEM_FIELDS,
    LINE_ITEM_FRAGMENT,
    MAILING_ADDRESS_FRAGMENT,
    METAFIELD_CONNECTIONS_FRAGMENT,
    METAFIELD_FIELDS,
    MONEY_BAG_FRAGMENT,
    MONEY_V2_FRAGMENT,
    NODE_CONNECTION_ID_FRAGMENT,
    TAX_LINES_FRAGMENT,
)

ORDERS_SORTKEY = "UPDATED_AT"

# Fields gated behind scopes beyond `read_orders` -> scopes that unlock them (any one suffices).
# Lets a `read_orders`-only token still import the rest of the order instead of "Access denied".
ORDERS_PROTECTED_FIELDS: dict[str, set[str]] = {
    "fulfillmentOrders": {
        "read_merchant_managed_fulfillment_orders",
        "read_third_party_fulfillment_orders",
        "read_assigned_fulfillment_orders",
    },
    "paymentTerms": {"read_payment_terms"},
}

_FULFILLMENT_ORDERS_BLOCK = f"fulfillmentOrders(first: 250) {NODE_CONNECTION_ID_FRAGMENT}"

_PAYMENT_TERMS_BLOCK = f"""paymentTerms {{
                due
                dueInDays
                id
                order {ID_NAME_CREATED_UPDATED_FRAGMENT}
                overdue
                paymentTermsName
                paymentTermsType
                translatedName
            }}"""


_DISCOUNT_APPLICATIONS_BLOCK = f"""discountApplications(first: 250) {{
                nodes {{
                    allocationMethod
                    index
                    targetSelection
                    targetType
                    value {{
                        ... on MoneyV2 {MONEY_V2_FRAGMENT}
                        ... on PricingPercentageValue {{
                            percentage
                        }}
                    }}
                }}
            }}"""

_SHIPPING_LINES_BLOCK = f"""shippingLines(first: 250) {{
                nodes {{
                    id
                    carrierIdentifier
                    code
                    currentDiscountedPriceSet {MONEY_BAG_FRAGMENT}
                    custom
                    deliveryCategory
                    discountedPriceSet {MONEY_BAG_FRAGMENT}
                    isRemoved
                    originalPriceSet {MONEY_BAG_FRAGMENT}
                    phone
                    shippingRateHandle
                    source
                    taxLines {TAX_LINES_FRAGMENT}
                    title
                }}
            }}"""

# NOTE: 250 is the max allowable query size for nested connections
_LINE_ITEMS_BLOCK = f"""lineItems(first: 250) {{
                nodes {LINE_ITEM_FRAGMENT}
            }}"""

_METAFIELDS_BLOCK = f"metafields(first: 250) {METAFIELD_CONNECTIONS_FRAGMENT}"

# The nested connections a bulk operation can export, keyed by the `__typename` of their rows.
# A bulk operation writes each nested row on its own line, and the type is the only thing on that
# line that says which connection of the order the row belongs to.
ORDERS_BULK_CONNECTIONS: dict[str, str] = {"LineItem": "lineItems", "Metafield": "metafields"}

_BULK_LINE_ITEMS_BLOCK = f"""lineItems {{
                edges {{
                    node {{
                        __typename{LINE_ITEM_FIELDS}                    }}
                }}
            }}"""

_BULK_METAFIELDS_BLOCK = f"""metafields {{
                edges {{
                    node {{
                        __typename{METAFIELD_FIELDS}                    }}
                }}
            }}"""


def _order_fields(granted_scopes: set[str], bulk: bool = False) -> str:
    """The fields selected on each order.

    A bulk operation accepts only nested connections whose rows implement `Node`, at most five
    connections, and no `first` argument. The bulk selection therefore keeps `lineItems` and
    `metafields`, and leaves out `discountApplications`, `shippingLines`, `events` and
    `fulfillmentOrders`.
    """
    fulfillment_orders = (
        _FULFILLMENT_ORDERS_BLOCK if not bulk and granted_scopes & ORDERS_PROTECTED_FIELDS["fulfillmentOrders"] else ""
    )
    payment_terms = _PAYMENT_TERMS_BLOCK if granted_scopes & ORDERS_PROTECTED_FIELDS["paymentTerms"] else ""
    discount_applications = "" if bulk else _DISCOUNT_APPLICATIONS_BLOCK
    events = "" if bulk else f"events(first: 250) {NODE_CONNECTION_ID_FRAGMENT}"
    line_items = _BULK_LINE_ITEMS_BLOCK if bulk else _LINE_ITEMS_BLOCK
    metafields = _BULK_METAFIELDS_BLOCK if bulk else _METAFIELDS_BLOCK
    shipping_lines = "" if bulk else _SHIPPING_LINES_BLOCK

    return f"""
            id
            additionalFees {{
                id
                name
                price {MONEY_BAG_FRAGMENT}
                taxLines {TAX_LINES_FRAGMENT}
            }}
            app {ID_NAME_FRAGMENT}
            billingAddress {MAILING_ADDRESS_FRAGMENT}
            billingAddressMatchesShippingAddress
            cancellation {{
                staffNote
            }}
            cancelledAt
            cancelReason
            cartDiscountAmountSet {MONEY_BAG_FRAGMENT}
            closed
            closedAt
            confirmationNumber
            confirmed
            createdAt
            currencyCode
            currentCartDiscountAmountSet {MONEY_BAG_FRAGMENT}
            currentShippingPriceSet {MONEY_BAG_FRAGMENT}
            currentSubtotalLineItemsQuantity
            currentSubtotalPriceSet {MONEY_BAG_FRAGMENT}
            currentTaxLines {TAX_LINES_FRAGMENT}
            currentTotalAdditionalFeesSet {MONEY_BAG_FRAGMENT}
            currentTotalDiscountsSet {MONEY_BAG_FRAGMENT}
            currentTotalDutiesSet {MONEY_BAG_FRAGMENT}
            currentTotalPriceSet {MONEY_BAG_FRAGMENT}
            currentTotalTaxSet {MONEY_BAG_FRAGMENT}
            currentTotalWeight
            customAttributes {KV_FRAGMENT}
            customer {CUSTOMER_FRAGMENT}
            customerLocale
            {discount_applications}
            discountCodes
            displayAddress {MAILING_ADDRESS_FRAGMENT}
            displayFinancialStatus
            displayFulfillmentStatus
            disputes {{
                id
                initiatedAs
                status
            }}
            dutiesIncluded
            edited
            email
            estimatedTaxes
            {events}
            fulfillable
            {fulfillment_orders}
            fulfillments(first: 250) {{
                id
                createdAt
                deliveredAt
                displayStatus
                estimatedDeliveryAt
                inTransitAt
                name
                requiresShipping
                status
                service {{
                    id
                    handle
                    serviceName
                    trackingSupport
                    type
                }}
                totalQuantity
                trackingInfo {{
                    company
                    number
                    url
                }}
                updatedAt
            }}
            fulfillmentsCount {COUNT_FRAGMENT}
            fullyPaid
            legacyResourceId
            {line_items}
            {metafields}
            name
            netPaymentSet {MONEY_BAG_FRAGMENT}
            note
            number
            originalTotalAdditionalFeesSet {MONEY_BAG_FRAGMENT}
            originalTotalDutiesSet {MONEY_BAG_FRAGMENT}
            originalTotalPriceSet {MONEY_BAG_FRAGMENT}
            paymentGatewayNames
            {payment_terms}
            phone
            poNumber
            presentmentCurrencyCode
            processedAt
            refundable
            refunds(first: 250) {{
                id
                createdAt
                note
                totalRefundedSet {MONEY_BAG_FRAGMENT}
                updatedAt
            }}
            refundDiscrepancySet {MONEY_BAG_FRAGMENT}
            requiresShipping
            returnStatus
            shippingAddress {MAILING_ADDRESS_FRAGMENT}
            {shipping_lines}
            sourceIdentifier
            sourceName
            subtotalLineItemsQuantity
            subtotalPriceSet {MONEY_BAG_FRAGMENT}
            tags
            taxesIncluded
            taxExempt
            taxLines {TAX_LINES_FRAGMENT}
            test
            totalCapturableSet {MONEY_BAG_FRAGMENT}
            totalDiscountsSet {MONEY_BAG_FRAGMENT}
            totalOutstandingSet {MONEY_BAG_FRAGMENT}
            totalPriceSet {MONEY_BAG_FRAGMENT}
            totalRefundedSet {MONEY_BAG_FRAGMENT}
            totalRefundedShippingSet {MONEY_BAG_FRAGMENT}
            totalShippingPriceSet {MONEY_BAG_FRAGMENT}
            totalTaxSet {MONEY_BAG_FRAGMENT}
            totalTipReceivedSet {MONEY_BAG_FRAGMENT}
            totalWeight
            unpaid
            updatedAt
            transactions(first: 250) {{
                id
                amountSet {MONEY_BAG_FRAGMENT}
                createdAt
                gateway
                kind
                processedAt
                status
            }}"""


def build_orders_query(granted_scopes: set[str]) -> str:
    """Orders query with each protected-field selection included only when its scope is granted."""
    return f"""
query PaginatedOrders($pageSize: Int!, $cursor: String, $query: String) {{
    orders(
        first: $pageSize, after: $cursor, sortKey: {ORDERS_SORTKEY},
        query: $query
    ) {{
        nodes {{{_order_fields(granted_scopes)}
        }}
        pageInfo {{
            hasNextPage
            endCursor
        }}
    }}
}}"""


def build_orders_bulk_query(granted_scopes: set[str], search_query: str | None = None) -> str:
    """The orders query for `bulkOperationRunQuery`, which takes no variables and no page size."""
    arguments = f"sortKey: {ORDERS_SORTKEY}"
    if search_query:
        # A JSON string literal is also a valid GraphQL string literal.
        arguments += f", query: {json.dumps(search_query)}"
    return f"""
{{
    orders({arguments}) {{
        edges {{
            node {{{_order_fields(granted_scopes, bulk=True)}
            }}
        }}
    }}
}}"""


# Full query (all scopes granted); the sync path rebuilds it from the token's real scopes.
ORDERS_QUERY = build_orders_query({scope for scopes in ORDERS_PROTECTED_FIELDS.values() for scope in scopes})
