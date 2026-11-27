from products.warehouse_sources.sources.sdk import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "orders_with_journeys": {
        "description": "Orders with customer journeys and Triple Pixel attribution.",
        "docs_url": "https://triplewhale.readme.io/reference/get-customer-journey-attribution-data",
        "columns": {
            "order_id": "Unique order identifier from the commerce platform.",
            "created_at": "Time when the order was created, in ISO 8601 format.",
            "order_name": "Order name from the commerce platform.",
            "customer_id": "Identifier of the customer who placed the order.",
            "total_price": "Total order price in the specified currency.",
            "currency": "Currency code for the order price.",
            "attribution": "Marketing sources and campaign, ad set, and ad identifiers credited for the order.",
            "journey": "Customer events before the order, including page views and cart additions.",
        },
    },
    "summary_page": {
        "description": "Daily Summary Page metrics for sales and marketing performance.",
        "docs_url": "https://triplewhale.readme.io/reference/get-summary-page-data",
        "columns": {
            "date": "Date of the requested daily reporting period.",
            "metricName": "Name of the Summary Page metric.",
            "value": "Metric value for the requested day.",
        },
    },
    "orders": {
        "description": "One row per order across all connected sales platforms and marketplaces.",
        "docs_url": "https://triplewhale.readme.io/docs/orders-table",
        "columns": {
            "order_id": "Unique identifier of the order on its sales platform.",
            "platform": "Sales platform or marketplace the order came from.",
            "event_date": "Date the order was placed, in the shop time zone.",
            "created_at": "Time when the order was created.",
            "is_new_customer": "Whether this is the customer's first order.",
            "order_revenue": "Revenue of the order.",
            "gross_product_sales": "Product sales before discounts and refunds.",
            "discount_amount": "Total discount applied to the order.",
            "refund_money": "Amount refunded for the order, keyed to the order date.",
            "products_info": "Products in the order, with product, variant, quantity, and price details.",
        },
    },
    "ads": {
        "description": "Daily advertising performance reported by each connected ad platform, one row per ad, day, and breakdown.",
        "docs_url": "https://triplewhale.readme.io/docs/ads-table",
        "columns": {
            "event_date": "Date of the ad activity, in the shop time zone.",
            "channel": "Ad platform that reported the data, such as facebook-ads or google-ads.",
            "ad_id": "Identifier of the ad on the ad platform.",
            "breakdown_dimension": "Facebook Ads breakdown dimension for this row. Empty for ad totals.",
            "breakdown_value": "Value of the Facebook Ads breakdown dimension for this row.",
            "spend": "Amount spent on the ad for the day.",
            "impressions": "Number of times the ad was shown.",
            "clicks": "Number of clicks on the ad.",
            "conversion_value": "Conversion value reported by the ad platform.",
        },
    },
    "customers": {
        "description": "Customer profiles from sales and email/SMS platforms, one row per customer per platform.",
        "docs_url": "https://triplewhale.readme.io/docs/customers-table",
        "columns": {
            "customer_id": "Identifier of the customer on its platform.",
            "customer_id_key": "Customer key that joins to orders.",
            "platform": "Platform the customer profile comes from.",
            "created_at": "Time when the customer was created.",
            "email_address": "Customer email address. Blocked unless the API key has Customer PII read access.",
            "amount_spent": "Total amount spent by the customer.",
            "orders": "Total number of orders placed by the customer.",
        },
    },
    "products": {
        "description": "Product catalog from the connected sales platform, one row per product.",
        "docs_url": "https://triplewhale.readme.io/docs/products-table",
        "columns": {
            "product_id": "Identifier of the product on its sales platform.",
            "product_name": "Name of the product.",
            "product_status": "Status of the product on the sales platform.",
            "product_inventory_quantity": "Inventory quantity across all variants.",
            "variants": "Product variants, with SKU, price, and inventory quantity.",
        },
    },
}
