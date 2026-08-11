from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Project": {
        "description": "The Framer project (site), including its current production and staging publish state.",
        "docs_url": "https://www.framer.com/developers/server-api-reference",
        "columns": {
            "id": "Unique identifier of the Framer project.",
            "name": "Display name of the project.",
            "apiVersion1Id": "Hashed project id served by API version 1, kept for migration purposes.",
            "production": "Current production publish: deployment time, optimization status, site URL, and current page URL. Null when never published to production.",
            "staging": "Current staging publish: deployment time, optimization status, site URL, and current page URL. Null when never published to staging.",
        },
    },
    "Pages": {
        "description": "Web pages in the project's site tree.",
        "docs_url": "https://www.framer.com/developers/reference",
        "columns": {
            "id": "Unique identifier of the page node.",
            "path": "URL path of the page (for example /about or /blog/:slug). Null for the home page.",
            "collectionId": "For CMS-driven pages, the id of the CMS collection backing the page. Null for static pages.",
            "draft": "Whether the page is a draft and excluded from publishing.",
        },
    },
    "Collections": {
        "description": "CMS collections in the project, with their field definitions.",
        "docs_url": "https://www.framer.com/developers/cms",
        "columns": {
            "id": "Unique identifier of the collection.",
            "name": "Display name of the collection.",
            "slugFieldName": "Name of the field used to generate item slugs, if any.",
            "slugFieldBasedOn": "Field the slug value is derived from, if any.",
            "readonly": "Whether the collection is read-only in the Framer UI.",
            "managedBy": "Who manages the collection: the user, or the plugin that owns it.",
            "fields": "Field definitions of the collection (id, name, and type per field).",
        },
    },
    "CollectionItems": {
        "description": "Items (entries) across every CMS collection in the project.",
        "docs_url": "https://www.framer.com/developers/cms",
        "columns": {
            "id": "Identifier of the item: the external id when the item is plugin-managed, otherwise the node id.",
            "nodeId": "Internal node id of the item.",
            "collectionId": "Id of the collection the item belongs to.",
            "collectionName": "Name of the collection the item belongs to.",
            "slug": "URL slug of the item.",
            "slugByLocale": "Localized slugs keyed by locale id.",
            "draft": "Whether the item is a draft and excluded from publishing.",
            "createdAt": "When the item was created.",
            "updatedAt": "When the item was last updated.",
            "fieldData": "The item's field values keyed by field name (falling back to field id on name collisions).",
        },
    },
    "Locales": {
        "description": "Locales configured for the project's localization.",
        "docs_url": "https://www.framer.com/developers/localization",
        "columns": {
            "id": "Unique identifier of the locale.",
            "code": "Locale code (for example en-US).",
            "name": "Display name of the locale.",
            "slug": "URL slug prefix of the locale.",
        },
    },
    "Redirects": {
        "description": "URL redirects configured on the site.",
        "docs_url": "https://www.framer.com/developers/reference",
        "columns": {
            "id": "Unique identifier of the redirect.",
            "from": "Source path pattern being redirected.",
            "to": "Destination path or URL.",
        },
    },
    "Deployments": {
        "description": "Deployments (publishes) of the site on the active branch, newest first.",
        "docs_url": "https://www.framer.com/developers/server-api-reference",
        "columns": {
            "id": "Unique identifier of the deployment.",
            "status": "Deployment status: pending, optimizing, ready, or failed.",
            "failureStage": "For failed deployments, the stage that failed: publish or optimization.",
            "deployedBy": "The user who triggered the deployment, if known.",
            "createdAt": "When the deployment was created.",
            "updatedAt": "When the deployment last changed.",
            "versionUrl": "URL of the versioned deployment, when available.",
        },
    },
}
