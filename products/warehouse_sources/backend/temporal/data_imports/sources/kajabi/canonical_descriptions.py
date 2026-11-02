from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contacts": {
        "description": "Contacts and their profile, subscription status, and custom fields.",
        "docs_url": "https://developers.kajabi.com/api-reference/contacts/list-contacts",
        "columns": {
            "id": "Kajabi contact ID.",
            "email": "Contact email address.",
            "subscribed": "Whether the contact subscribes to marketing emails.",
            "created_at": "Time when Kajabi created the contact.",
            "relationships": "Links to the contact's site, customer, tags, and offers.",
        },
    },
    "customers": {
        "description": "Customer profiles, activity, and total revenue.",
        "docs_url": "https://developers.kajabi.com/api-reference/customers/list-customers",
        "columns": {
            "id": "Kajabi customer ID.",
            "email": "Customer email address.",
            "net_revenue": "Customer net revenue.",
            "relationships": "Links to the customer's contact, site, offers, and products.",
        },
    },
    "purchases": {
        "description": "Offer purchases with payment amounts, attribution, and access status.",
        "docs_url": "https://developers.kajabi.com/api-reference/purchases/list-purchases",
        "columns": {
            "id": "Kajabi purchase ID.",
            "amount_in_cents": "Purchase amount in cents.",
            "currency": "Purchase currency.",
            "coupon_code": "Coupon code used for the purchase.",
            "source": "Purchase source.",
            "referrer": "Purchase referrer.",
            "deactivated_at": "Time when Kajabi deactivated purchase access.",
        },
    },
    "offers": {
        "description": "Offers with prices, payment types, and checkout URLs.",
        "docs_url": "https://developers.kajabi.com/api-reference/offers/list-offers",
        "columns": {"id": "Kajabi offer ID.", "price_in_cents": "Offer price in cents.", "currency": "Offer currency."},
    },
    "products": {
        "description": "Products that can be granted to contacts, excluding archived products.",
        "docs_url": "https://developers.kajabi.com/api-reference/products/list-products",
        "columns": {
            "id": "Kajabi product ID.",
            "title": "Product title.",
            "publish_status": "Product publication status.",
        },
    },
    "courses": {
        "description": "Course titles, descriptions, and thumbnails.",
        "docs_url": "https://developers.kajabi.com/api-reference/courses/list-courses",
        "columns": {"id": "Kajabi course ID.", "title": "Course title."},
    },
    "orders": {
        "description": "Orders with totals, discounts, taxes, and fulfillment status.",
        "docs_url": "https://developers.kajabi.com/api-reference/orders/list-orders",
        "columns": {
            "id": "Kajabi order ID.",
            "order_number": "Order number.",
            "total_price_in_cents": "Order total in cents.",
        },
    },
    "order_items": {
        "description": "Order items with quantities, prices, discounts, and taxes.",
        "docs_url": "https://developers.kajabi.com/api-reference/orders/list-order-items",
        "columns": {
            "id": "Kajabi order item ID.",
            "quantity": "Item quantity.",
            "relationships": "Links to the order and purchased item.",
        },
    },
    "transactions": {
        "description": "Payment transactions with amounts, currencies, and payment states.",
        "docs_url": "https://developers.kajabi.com/api-reference/transactions/list-transactions",
        "columns": {
            "id": "Kajabi transaction ID.",
            "amount_in_cents": "Transaction amount in cents.",
            "state": "Transaction payment state.",
            "relationships": "Links to the customer and purchases covered by this transaction.",
        },
    },
    "contact_tags": {
        "description": "Tags available for contacts on the selected site.",
        "docs_url": "https://developers.kajabi.com/api-reference/contact-tags/list-contact-tags",
        "columns": {"id": "Kajabi contact tag ID.", "name": "Tag name."},
    },
    "contact_offers": {
        "description": "Offers granted to each contact on the selected site.",
        "docs_url": "https://developers.kajabi.com/api-reference/contacts/list-contacts-offers",
        "columns": {"contact_id": "Kajabi contact ID.", "id": "Kajabi offer ID."},
    },
    "contact_taggings": {
        "description": "Tags assigned to each contact on the selected site.",
        "docs_url": "https://developers.kajabi.com/api-reference/contacts/list-contacts-tags",
        "columns": {"contact_id": "Kajabi contact ID.", "id": "Kajabi contact tag ID."},
    },
}
