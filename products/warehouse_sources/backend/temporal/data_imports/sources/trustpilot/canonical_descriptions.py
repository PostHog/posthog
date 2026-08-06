"""Canonical, documentation-sourced descriptions for Trustpilot endpoints and columns.

Sourced from Trustpilot's Business Units, Service Reviews and Product Reviews API references
(https://developers.trustpilot.com). Keyed by the endpoint names in `settings.py`
`TRUSTPILOT_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced table. Columns absent
here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "business_units": {
        "description": "The Trustpilot business unit (company profile) this source is connected to, with its aggregate rating and review counts.",
        "docs_url": "https://developers.trustpilot.com/business-units-api",
        "columns": {
            "id": "Trustpilot's unique identifier for the business unit.",
            "displayName": "Business name as shown on the Trustpilot profile.",
            "name": "Identifying and referring names (domains) associated with the business unit.",
            "websiteUrl": "Website the business unit represents.",
            "country": "ISO 3166-1 alpha-2 country code the business unit is registered in.",
            "numberOfReviews": "Review counts, including the total and a breakdown by star rating.",
            "trustScore": "Trustpilot TrustScore for the business unit, from 1 to 5.",
            "stars": "TrustScore rounded to the nearest half star.",
            "status": "Whether the profile is claimed and active on Trustpilot.",
            "links": "HATEOAS navigation links to related Trustpilot resources.",
        },
    },
    "service_reviews": {
        "description": "Service reviews left by consumers on the business unit's Trustpilot profile.",
        "docs_url": "https://developers.trustpilot.com/service-reviews-api",
        "columns": {
            "id": "Unique identifier for the review.",
            "stars": "Star rating the consumer gave, from 1 to 5.",
            "title": "Title of the review.",
            "text": "Body text of the review.",
            "language": "ISO 639-1 language code the review was written in.",
            "createdAt": "When the review was created on Trustpilot.",
            "experiencedAt": "Date the consumer says they had the experience being reviewed.",
            "updatedAt": "When the review was last updated.",
            "numberOfLikes": "How many times the review has been liked.",
            "isVerified": "Whether the review is verified.",
            "status": "Moderation status of the review, such as active.",
            "companyReply": "The business's public reply to the review, if any (also synced as the review_replies table).",
            "consumer": "The consumer who wrote the review (id and display name).",
            "countsTowardsTrustScore": "Whether the review contributes to the business unit's TrustScore.",
            "reviewVerificationLevel": "How the reviewer's identity and experience were verified.",
        },
    },
    "product_reviews": {
        "description": "Reviews of individual products sold by the business unit.",
        "docs_url": "https://developers.trustpilot.com/product-reviews-api",
        "columns": {
            "id": "Unique identifier for the product review.",
            "createdAt": "When the product review was created.",
            "stars": "Star rating the consumer gave the product, from 1 to 5.",
            "content": "Body text of the product review.",
            "title": "Title of the product review.",
            "language": "ISO 639-1 language code the review was written in.",
            "consumer": "The consumer who wrote the review (id and display name).",
            "attributeRatings": "Per-attribute ratings the consumer gave (attribute id, name and rating).",
            "attachments": "Images or files the consumer attached to the review.",
            "firstCompanyComment": "The business's first public comment on the product review, if any.",
        },
    },
    "review_replies": {
        "description": "The business's public replies to its service reviews, one row per replied-to review, lifted from each review's companyReply.",
        "docs_url": "https://developers.trustpilot.com/service-reviews-api",
        "columns": {
            "review_id": "Identifier of the service review this reply answers.",
            "business_unit_id": "Identifier of the business unit that posted the reply.",
            "text": "Body text of the reply.",
            "createdAt": "When the reply was posted.",
            "updatedAt": "When the reply was last updated.",
        },
    },
}
