from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

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
}
