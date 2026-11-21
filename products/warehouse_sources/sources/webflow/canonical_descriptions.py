"""Canonical, documentation-sourced descriptions for Webflow endpoints and columns.

Sourced from the official Webflow Data API v2 reference (https://developers.webflow.com/data/reference).
Keyed by the static endpoint names in `settings.py` (`WEBFLOW_ENDPOINTS` and `ANALYZE_REPORTS`), which match the
`ExternalDataSchema.name` of a synced Webflow table. The per-site `collection_<slug>` schemas are
user-defined CMS collections discovered at sync time, so they intentionally have no canonical entry
and fall back to LLM enrichment. Columns absent here also fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sites": {
        "description": "A Webflow site, including its metadata and publishing details.",
        "docs_url": "https://developers.webflow.com/data/reference/sites/get",
        "columns": {
            "id": "Unique identifier for the site.",
            "displayName": "Human-readable name of the site.",
            "shortName": "Short, slug-like name of the site.",
            "previewUrl": "URL of the site's preview image.",
            "timeZone": "The site's configured time zone.",
            "createdOn": "Time at which the site was created.",
            "lastPublished": "Time at which the site was last published.",
            "lastUpdated": "Time at which the site was last updated.",
            "customDomains": "Custom domains attached to the site.",
        },
    },
    "collections": {
        "description": "A Webflow CMS collection (a content type) defined on the site.",
        "docs_url": "https://developers.webflow.com/data/reference/cms/collections/list",
        "columns": {
            "id": "Unique identifier for the collection.",
            "displayName": "Human-readable name of the collection.",
            "singularName": "Singular name for a single item in the collection.",
            "slug": "URL-friendly slug for the collection.",
            "createdOn": "Time at which the collection was created.",
            "lastUpdated": "Time at which the collection was last updated.",
        },
    },
    "pages": {
        "description": "A static page within a Webflow site.",
        "docs_url": "https://developers.webflow.com/data/reference/pages/list",
        "columns": {
            "id": "Unique identifier for the page.",
            "siteId": "ID of the site the page belongs to.",
            "title": "The page's title.",
            "slug": "URL slug of the page.",
            "parentId": "ID of the parent page, if the page is nested.",
            "createdOn": "Time at which the page was created.",
            "lastUpdated": "Time at which the page was last updated.",
            "archived": "Whether the page is archived.",
            "draft": "Whether the page is a draft.",
            "seo": "SEO metadata (title, description) for the page.",
        },
    },
    "products": {
        "description": "An ecommerce product in a Webflow site, with its associated SKUs.",
        "docs_url": "https://developers.webflow.com/data/reference/ecommerce/products/list",
        "columns": {
            "id": "Unique identifier for the product.",
            "fieldData": "The product's content fields (name, slug, description, etc.).",
            "skus": "The SKUs (variants) available for this product.",
            "createdOn": "Time at which the product was created.",
            "lastUpdated": "Time at which the product was last updated.",
            "isArchived": "Whether the product is archived.",
            "isDraft": "Whether the product is a draft.",
        },
    },
    "orders": {
        "description": "A customer order placed through a Webflow ecommerce site.",
        "docs_url": "https://developers.webflow.com/data/reference/ecommerce/orders/list",
        "columns": {
            "orderId": "Unique identifier for the order.",
            "status": "Status of the order (e.g. pending, fulfilled, refunded).",
            "customerInfo": "Customer contact information for the order.",
            "purchasedItems": "Line items purchased in the order.",
            "netAmount": "Net amount of the order after discounts and refunds.",
            "totals": "Breakdown of order totals (subtotal, tax, shipping, total).",
            "customerPaid": "Total amount the customer paid for the order.",
            "shippingProvider": "Name of the shipping provider for the order.",
            "shippingTracking": "Tracking number for the order's shipment.",
            "acceptedOn": "Time at which the order was accepted.",
            "fulfilledOn": "Time at which the order was fulfilled.",
            "refundedOn": "Time at which the order was refunded, if applicable.",
        },
    },
    "users": {
        "description": "A registered user (site member) of a Webflow site.",
        "docs_url": "https://developers.webflow.com/data/reference/users/list",
        "columns": {
            "id": "Unique identifier for the user.",
            "isEmailVerified": "Whether the user's email address has been verified.",
            "status": "Account status of the user (e.g. verified, invited, unverified).",
            "accessGroups": "Access groups the user belongs to.",
            "data": "Custom user data fields (name, email, accept-privacy, etc.).",
            "createdOn": "Time at which the user account was created.",
            "lastUpdated": "Time at which the user account was last updated.",
            "lastLogin": "Time at which the user last logged in.",
        },
    },
    "forms": {
        "description": "A form definition configured on a Webflow site.",
        "docs_url": "https://developers.webflow.com/data/reference/forms/list-forms",
        "columns": {
            "id": "Unique identifier for the form.",
            "displayName": "Human-readable name of the form.",
            "siteId": "ID of the site the form belongs to.",
            "pageId": "ID of the page the form appears on.",
            "fields": "The fields that make up the form.",
            "responseSettings": "Settings controlling how form responses are handled.",
            "createdOn": "Time at which the form was created.",
            "lastUpdated": "Time at which the form was last updated.",
        },
    },
    "form_submissions": {
        "description": "A submission of a form on a Webflow site, with the data the visitor entered.",
        "docs_url": "https://developers.webflow.com/data/reference/forms/form-submissions/list-submissions-by-site",
        "columns": {
            "id": "Unique identifier for the form submission.",
            "displayName": "Name of the form, as displayed on the site.",
            "siteId": "ID of the site the form belongs to.",
            "workspaceId": "ID of the workspace the site belongs to.",
            "dateSubmitted": "Time at which the form was submitted.",
            "formResponse": "The data submitted in the form, keyed by field name.",
            "localeId": "ID of the locale the form was submitted from. Null for the primary locale.",
        },
    },
    "analyze_traffic": {
        "description": "Daily site traffic from Webflow Analyze: sessions, unique users and page views per UTC day.",
        "docs_url": "https://developers.webflow.com/data/reference/analyze/traffic",
        "columns": {
            "timestamp": "Start of the UTC day the counts cover.",
            "sessionCount": "Number of sessions on the day.",
            "userCount": "Number of unique users on the day.",
            "pageviewCount": "Number of page views on the day.",
        },
    },
    "analyze_top_pages": {
        "description": "The most visited pages of the site per UTC day from Webflow Analyze, up to 250 pages a day ranked by sessions.",
        "docs_url": "https://developers.webflow.com/data/reference/analyze/top-pages",
        "columns": {
            "timestamp": "Start of the UTC day the counts cover.",
            "pageId": "ID of the Webflow page.",
            "title": "Display title of the page, or the CMS item name for a CMS-templated page.",
            "sessionCount": "Sessions attributed to the page on the day.",
            "userCount": "Unique users that visited the page on the day.",
            "pageviewCount": "Page views recorded for the page on the day.",
            "collectionId": "ID of the CMS collection of a CMS-templated page.",
            "itemSlug": "Slug of the CMS item for a CMS-templated page. Empty for other pages.",
        },
    },
    "analyze_time_on_page": {
        "description": "Daily average time on page across the whole site from Webflow Analyze, per UTC day.",
        "docs_url": "https://developers.webflow.com/data/reference/analyze/time-on-page",
        "columns": {
            "timestamp": "Start of the UTC day the averages cover.",
            "averageSecondsPerSession": "Average time on page per session, in seconds.",
            "averageSecondsPerUser": "Average time on page per unique user, in seconds.",
            "averageSecondsPerPageview": "Average time on page per page view, in seconds.",
        },
    },
}
