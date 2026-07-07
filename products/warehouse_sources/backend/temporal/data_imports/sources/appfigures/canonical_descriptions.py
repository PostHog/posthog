from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions taken from the Appfigures v2 API docs (https://docs.appfigures.com/api/reference/v2).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "products": {
        "description": "Apps, games, books, and other content in your Appfigures account, each with an Appfigures-assigned product id that is consistent across stores.",
        "docs_url": "https://docs.appfigures.com/api/reference/v2/products",
        "columns": {
            "id": "The product's unique, Appfigures-assigned id.",
            "name": "Full product name.",
            "developer": "Developer name.",
            "icon": "URL of the product's store icon.",
            "vendor_identifier": "The ref_no or sku the store uses to uniquely identify this product.",
            "ref_no": "Store id of the product (currently Apple only).",
            "sku": "Developer-assigned SKU or package name.",
            "store_id": "Numeric id of the store the product belongs to.",
            "store": "Name of the store (e.g. apple, google_play, amazon_appstore).",
            "release_date": "Date the product was released to the store.",
            "added_date": "Date the product was added by Appfigures.",
            "updated_date": "Date the product was last updated.",
            "version": "Current version of the product.",
            "type": "Product type: app, inapp, or book.",
            "active": "Whether the product is currently active in the store.",
            "parent_id": "Product id of the parent product, for in-app purchases and child products.",
        },
    },
    "reviews": {
        "description": "App reviews across supported stores, filterable by product, country, stars, and creation date.",
        "docs_url": "https://docs.appfigures.com/api/reference/v2/reviews",
        "columns": {
            "id": "Unique review id.",
            "title": "Review title (translated when a language is requested).",
            "review": "Full review text (translated when a language is requested).",
            "original_title": "Pre-translation review title, if translated.",
            "original_review": "Pre-translation review text, if translated.",
            "author": "Review author name.",
            "version": "App version the review was left on, if the store provides it.",
            "date": "Date and time the review was left.",
            "stars": "Star rating given in the review.",
            "iso": "Country code of the review (iOS/Mac only; Google Play reviews are set to ZZ).",
            "product": "Appfigures product id the review belongs to.",
            "has_response": "Whether the developer responded to the review through Appfigures.",
            "predicted_langs": "Algorithm-predicted language(s) of the review.",
        },
    },
    "sales_report": {
        "description": "Daily sales report aggregated across the account — downloads, updates, re-downloads, and related unit counts, one row per day.",
        "docs_url": "https://docs.appfigures.com/api/reference/v2/sales",
        "columns": {
            "date": "Calendar day the metrics cover (yyyy-mm-dd).",
            "downloads": "Total downloads on the day.",
            "net_downloads": "Downloads net of returns.",
            "updates": "App updates on the day.",
            "re_downloads": "Re-downloads on the day.",
            "uninstalls": "Uninstalls on the day, where reported.",
            "revenue": "Revenue recognized on the day.",
            "returns": "Number of returns on the day.",
        },
    },
    "revenue_report": {
        "description": "Daily revenue report aggregated across the account, one row per day.",
        "docs_url": "https://docs.appfigures.com/api/reference/v2/revenue",
        "columns": {
            "date": "Calendar day the metrics cover (yyyy-mm-dd).",
            "revenue": "Total revenue recognized on the day.",
            "app_revenue": "Revenue from paid app downloads.",
            "gross_revenue": "Revenue before store commission.",
        },
    },
}
