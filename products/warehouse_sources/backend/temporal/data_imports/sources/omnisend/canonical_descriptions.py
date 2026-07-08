"""Canonical, documentation-sourced descriptions for Omnisend endpoints and columns.

Sourced from the official Omnisend API reference (https://api-docs.omnisend.com/reference).
Keyed by the endpoint names in `settings.py` `OMNISEND_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Omnisend table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contacts": {
        "description": "A contact in Omnisend — a subscriber with channel statuses and profile attributes.",
        "docs_url": "https://api-docs.omnisend.com/reference/get-contacts",
        "columns": {
            "contactID": "Unique identifier for the contact.",
            "email": "The contact's email address.",
            "phone": "The contact's phone number.",
            "firstName": "The contact's first name.",
            "lastName": "The contact's last name.",
            "status": "Subscription status of the contact (e.g. subscribed, unsubscribed, nonSubscribed).",
            "statusDate": "Time at which the contact's status last changed.",
            "tags": "Tags applied to the contact.",
            "customProperties": "Custom attributes stored on the contact.",
            "createdAt": "Time at which the contact was created.",
            "updatedAt": "Time at which the contact was last updated.",
        },
    },
    "campaigns": {
        "description": "An email or SMS campaign sent through Omnisend.",
        "docs_url": "https://api-docs.omnisend.com/reference/get-campaigns",
        "columns": {
            "campaignID": "Unique identifier for the campaign.",
            "name": "The campaign's name.",
            "subject": "Subject line of the campaign.",
            "fromName": "Sender name shown to recipients.",
            "fromEmail": "Sender email address.",
            "type": "Type of campaign (e.g. email, sms).",
            "status": "Status of the campaign (e.g. draft, sending, sent).",
            "createdAt": "Time at which the campaign was created.",
            "startDate": "Time at which the campaign was or is scheduled to start sending.",
        },
    },
    "carts": {
        "description": "A shopping cart tracked in Omnisend, used for abandoned-cart automations.",
        "docs_url": "https://api-docs.omnisend.com/reference/get-carts",
        "columns": {
            "cartID": "Unique identifier for the cart.",
            "contactID": "Identifier of the contact the cart belongs to.",
            "email": "Email address associated with the cart.",
            "currency": "Three-letter ISO currency code of the cart.",
            "cartSum": "Total value of the cart.",
            "products": "Line items (products) in the cart.",
            "cartRecoveryUrl": "URL the contact can use to recover the cart.",
            "createdAt": "Time at which the cart was created.",
            "updatedAt": "Time at which the cart was last updated.",
        },
    },
    "orders": {
        "description": "An order placed by a contact, tracked in Omnisend for purchase-based automations.",
        "docs_url": "https://api-docs.omnisend.com/reference/get-orders",
        "columns": {
            "orderID": "Unique identifier for the order.",
            "contactID": "Identifier of the contact who placed the order.",
            "email": "Email address associated with the order.",
            "currency": "Three-letter ISO currency code of the order.",
            "orderSum": "Total value of the order.",
            "paymentStatus": "Payment status of the order (e.g. paid, awaitingPayment).",
            "fulfillmentStatus": "Fulfillment status of the order.",
            "products": "Line items (products) in the order.",
            "createdAt": "Time at which the order was created.",
            "updatedAt": "Time at which the order was last updated.",
        },
    },
    "products": {
        "description": "A product in the Omnisend catalog.",
        "docs_url": "https://api-docs.omnisend.com/reference/get-products",
        "columns": {
            "productID": "Unique identifier for the product.",
            "title": "The product's title.",
            "description": "Description of the product.",
            "status": "Status of the product (e.g. active, notAvailable).",
            "currency": "Three-letter ISO currency code for the product's prices.",
            "productUrl": "URL of the product page.",
            "imageUrl": "URL of the product's image.",
            "variants": "Variants of the product (e.g. sizes, colors) with their prices.",
            "categoryIDs": "Identifiers of the categories the product belongs to.",
            "createdAt": "Time at which the product was created.",
            "updatedAt": "Time at which the product was last updated.",
        },
    },
    "categories": {
        "description": "A product category in the Omnisend catalog.",
        "docs_url": "https://api-docs.omnisend.com/reference/get-categories",
        "columns": {
            "categoryID": "Unique identifier for the category.",
            "title": "The category's title.",
            "createdAt": "Time at which the category was created.",
            "updatedAt": "Time at which the category was last updated.",
        },
    },
}
