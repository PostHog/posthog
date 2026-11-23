from products.warehouse_sources.sources.sdk import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "reviews": {
        "description": "Product and site reviews submitted to the store.",
        "docs_url": "https://apidocs.yotpo.com/reference/retrieve-all-reviews",
        "columns": {
            "id": "The Yotpo review ID.",
            "created_at": "The time the review was created.",
            "updated_at": "The time the review was last updated.",
            "score": "The review's star rating.",
            "sku": "The product SKU associated with the review.",
            "deleted": "Whether the review is unpublished.",
        },
    },
    "email_analytics": {
        "description": "Daily counts of emails sent, grouped by email type.",
        "docs_url": "https://apidocs.yotpo.com/reference/email-analytics",
        "columns": {
            "since": "The first date included in this reporting period.",
            "until": "The last date included in this reporting period.",
            "values": "Email counts grouped by email type.",
        },
    },
    "raw_data": {
        "description": "Email delivery and engagement records.",
        "docs_url": "https://apidocs.yotpo.com/reference/raw-data",
        "columns": {
            "email_address": "The recipient's email address.",
            "email_type": "The type of email sent by Yotpo.",
            "email_sent_timestamp": "The time Yotpo sent the email.",
            "opened_timestamp": "The time the recipient opened the email.",
            "unsubscribed_timestamp": "The time the recipient unsubscribed.",
        },
    },
    "unsubscribers": {
        "description": "Email addresses excluded from Yotpo email distribution lists.",
        "docs_url": "https://apidocs.yotpo.com/reference/retrieve-a-list-of-unsubscribers",
        "columns": {
            "user_email": "The unsubscribed email address.",
            "email_type_id": "The email distribution list identifier.",
            "unsubscribed_by_name": "Who requested the unsubscribe action.",
        },
    },
    "orders": {
        "description": "Orders placed in the store, as synced to Yotpo.",
        "docs_url": "https://docs.yotpo.com/reference/retrieve-orders",
        "columns": {
            "yotpo_id": "The Yotpo ID of the order.",
            "external_id": "The order ID in the store's e-commerce platform.",
            "order_date": "When the order was placed in the store (UTC).",
            "total_price": "The order total including discounts, shipping, taxes and tips, in the order currency.",
            "subtotal_price": "The order price after discounts and before shipping, taxes and tips.",
            "currency": "The three-letter ISO currency code of the order.",
            "payment_status": "The payment status of the order, for example paid or refunded.",
            "customer": "The customer who placed the order.",
            "line_items": "The products in the order.",
            "fulfillments": "The fulfillments of the order.",
            "created_at": "When the order was created in Yotpo (UTC).",
            "updated_at": "When the order was last updated in Yotpo (UTC).",
        },
    },
    "products": {
        "description": "The store's product catalog, as synced to Yotpo.",
        "docs_url": "https://docs.yotpo.com/reference/retrieve-products",
        "columns": {
            "yotpo_id": "The Yotpo ID of the product.",
            "external_id": "The product ID in the store's e-commerce platform.",
            "name": "The product name.",
            "status": "The product status: active, draft, archived or inactive.",
            "price": "The product price, in the product currency.",
            "sku": "The product SKU.",
            "group_name": "The product group. Products in the same group share reviews.",
            "is_discontinued": "Whether the product is discontinued.",
            "created_at": "When the product was created in Yotpo (UTC).",
            "updated_at": "When the product was last updated in Yotpo (UTC).",
        },
    },
    "customers": {
        "description": "Store customers, with their Yotpo reviews and loyalty summaries.",
        "docs_url": "https://docs.yotpo.com/reference/retrieve-customers",
        "columns": {
            "external_id": "The customer ID in the store. Null when the customer was created by email only.",
            "email": "The customer's email address.",
            "phone_number": "The customer's phone number in E.164 format.",
            "account_created_at": "When the customer's account was created in the store (UTC).",
            "account_updated_at": "When the customer was last updated (UTC).",
            "yotpo_ugc": "The customer's reviews summary.",
            "yotpo_loyalty": "The customer's loyalty summary.",
        },
    },
    "customer_segments": {
        "description": "Customer segments and imported lists of the store.",
        "docs_url": "https://docs.yotpo.com/reference/list-customer-segments",
        "columns": {
            "id": "The ID of the segment.",
            "name": "The segment name.",
            "definition": "The rules that decide which customers are in the segment.",
            "type": "Whether the entry is a segment or a list.",
            "status": "The segment status.",
        },
    },
}
