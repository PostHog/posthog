from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Judge.me API docs (https://judge.me/api/docs).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "reviews": {
        "description": "A product or store review left by a shopper, including its rating, moderation state, and media.",
        "docs_url": "https://judge.me/api/docs",
        "columns": {
            "id": "Judge.me internal ID of the review.",
            "title": "Raw review title as submitted by the reviewer (not sanitized).",
            "body": "Raw review body as submitted by the reviewer (not sanitized).",
            "rating": "Star rating given by the reviewer, from 1 to 5.",
            "pinned": "Whether the review is pinned to the top of the review widget.",
            "product_external_id": "External (e.g. Shopify) ID of the reviewed product. Empty for store reviews.",
            "product_title": "Title of the reviewed product.",
            "product_handle": "URL handle of the reviewed product.",
            "reviewer": "The reviewer who left the review (internal ID, name, email, phone, tags).",
            "source": "Where the review originates (e.g. email, web). Some sources imply the review is verified.",
            "curated": "Curated status: ok (published on the storefront), spam (not published), or not-yet (awaiting curation).",
            "hidden": "Whether the review is archived to the Archived tab in the Reviews dashboard.",
            "verified": "Verified status of the review (e.g. buyer, confirmed-buyer, verified-purchase, nothing).",
            "created_at": "When the review was created.",
            "updated_at": "When the review was last updated.",
            "ip_address": "IP address the review was submitted from.",
            "has_published_pictures": "Whether the review contains published pictures.",
            "has_published_videos": "Whether the review contains published videos.",
            "pictures": "Pictures attached to the review, with per-size URLs and hidden flags.",
        },
    },
    "products": {
        "description": "A product known to Judge.me for this shop, mapping Judge.me internal product IDs to the external store catalog.",
        "docs_url": "https://judge.me/api/docs",
        "columns": {
            "id": "Judge.me internal ID of the product.",
            "external_id": "External (e.g. Shopify) ID of the product.",
            "title": "Title of the product.",
            "handle": "URL handle of the product.",
            "vendor": "Vendor of the product.",
            "product_type": "Type/category of the product.",
            "description": "Description of the product.",
            "in_store": "Whether the product is published on the storefront.",
            "excluded": "Whether Judge.me excludes this product from review request emails.",
            "image_url": "URL of the product image.",
        },
    },
}
