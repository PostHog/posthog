from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trustradius.settings import API_DOCS_URL

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "products": {
        "description": "Published products listed under the vendor profile.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "_id": "The product identifier for other TrustRadius API calls.",
            "slug": "The product name identifier used in TrustRadius URLs.",
            "vendor": "The identifier and name of the vendor.",
        },
    },
    "product_scores": {
        "description": "Product scores and review counts for products licensed for the API.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "The product identifier.",
            "name": "The product name.",
            "trScore": "The TrustRadius score and its maximum value.",
            "starScore": "The star score and its maximum value.",
            "reviewCount": "The number of reviews.",
            "ratingCount": "The number of ratings.",
            "ratingsAndReviewsTotalCount": "The combined number of ratings and reviews.",
            "url": "The product URL.",
        },
    },
    "trustquotes": {
        "description": "Quotes from product reviews, with reviewer details and assigned tags.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "The quote identifier.",
            "created": "The date when the quote was created.",
            "text": "The quote text.",
            "review": "The source review, including its rating and publication date.",
            "product": "The product identifier and name.",
            "vendor": "The vendor identifier and name.",
            "isAnonymous": "Whether the quote comes from an anonymous review.",
            "allTags": "The identifiers of the assigned tags.",
            "allTagNames": "The names of the assigned tags.",
        },
    },
    "tags": {
        "description": "Tags and tag groups used to classify TrustQuotes.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "The tag identifier.",
            "name": "The tag name.",
            "tagGroup": "The group that contains the tag.",
            "vendor": "The vendor identifier and name.",
            "products": "The identifiers and names of products associated with the tag.",
        },
    },
}
