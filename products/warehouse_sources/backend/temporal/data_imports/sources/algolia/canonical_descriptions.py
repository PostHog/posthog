from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the Algolia REST API reference (https://www.algolia.com/doc/rest-api/search/).
# `records` holds the user's own index objects, so its columns are index-specific and left to the
# LLM; only the universal `objectID` is documented here.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "records": {
        "description": "Every object stored in the Algolia index, retrieved via the browse endpoint.",
        "docs_url": "https://www.algolia.com/doc/rest-api/search/#tag/Records/operation/browse",
        "columns": {
            "objectID": "Unique identifier of the record within the index.",
        },
    },
    "synonyms": {
        "description": "Synonyms configured on the index, defining terms Algolia treats as equivalent at query time.",
        "docs_url": "https://www.algolia.com/doc/rest-api/search/#tag/Synonyms",
        "columns": {
            "objectID": "Unique identifier of the synonym.",
            "type": "Synonym type (e.g. synonym, oneWaySynonym, altCorrection1, placeholder).",
            "synonyms": "List of words considered equivalent.",
        },
    },
    "rules": {
        "description": "Query rules on the index that change ranking or results when a query matches their conditions.",
        "docs_url": "https://www.algolia.com/doc/rest-api/search/#tag/Rules",
        "columns": {
            "objectID": "Unique identifier of the rule.",
            "conditions": "Conditions that trigger the rule.",
            "consequence": "Effect applied to the query when the rule's conditions match.",
            "enabled": "Whether the rule is currently active.",
        },
    },
    "indices": {
        "description": "All indices on the Algolia application with their size and timing metadata.",
        "docs_url": "https://www.algolia.com/doc/rest-api/search/#tag/Indices/operation/listIndices",
        "columns": {
            "name": "Index name.",
            "entries": "Number of records in the index.",
            "dataSize": "Size of the index data in bytes.",
            "fileSize": "Total size of the index including metadata, in bytes.",
            "createdAt": "Date the index was created (ISO 8601).",
            "updatedAt": "Date the index was last updated (ISO 8601).",
            "primary": "Name of the primary index, set on replica indices.",
        },
    },
    "top_searches": {
        "description": "Most popular searches on the index over the recent period, with search volume and, "
        "when click analytics is enabled, click and conversion metrics.",
        "docs_url": "https://www.algolia.com/doc/rest-api/analytics/#tag/searches/operation/getTopSearches",
        "columns": {
            "search": "Search query term.",
            "count": "Number of searches for this term.",
            "nbHits": "Average number of search results (hits) returned for this term.",
            "trackedSearchCount": "Number of tracked searches (requests with click analytics enabled).",
            "clickCount": "Number of clicks on results for this term.",
            "clickThroughRate": "Click-through rate: clicks divided by tracked searches.",
            "averageClickPosition": "Average position of the clicked result.",
            "conversionCount": "Number of conversions attributed to this term.",
            "conversionRate": "Conversion rate: conversions divided by tracked searches.",
        },
    },
    "top_hits": {
        "description": "Most frequent search results (records) shown on the index over the recent period, with "
        "display volume and, when click analytics is enabled, click and conversion metrics.",
        "docs_url": "https://www.algolia.com/doc/rest-api/analytics/#tag/hits/operation/getTopHits",
        "columns": {
            "hit": "Object ID of the record returned as a search result.",
            "count": "Number of times this record appeared in search results.",
            "trackedHitCount": "Number of tracked searches that returned this record.",
            "clickCount": "Number of clicks on this record.",
            "clickThroughRate": "Click-through rate for this record.",
            "conversionCount": "Number of conversions attributed to this record.",
            "conversionRate": "Conversion rate for this record.",
        },
    },
    "searches_no_results": {
        "description": "Most frequent searches on the index that returned zero results over the recent period.",
        "docs_url": "https://www.algolia.com/doc/rest-api/analytics/#tag/searches/operation/getSearchesNoResults",
        "columns": {
            "search": "Search query term that returned no results.",
            "count": "Number of searches for this term.",
            "withFilterCount": "Number of those searches that had filters applied.",
        },
    },
    "searches_no_clicks": {
        "description": "Most popular searches on the index that led to no clicks over the recent period.",
        "docs_url": "https://www.algolia.com/doc/rest-api/analytics/#tag/searches/operation/getSearchesNoClicks",
        "columns": {
            "search": "Search query term that received no clicks.",
            "count": "Number of tracked searches for this term.",
            "nbHits": "Average number of search results shown that remained unclicked.",
        },
    },
    "ab_tests": {
        "description": "A/B tests configured on the application, each with its variants and per-variant results.",
        "docs_url": "https://www.algolia.com/doc/rest-api/abtesting/#tag/abtest/operation/listABTests",
        "columns": {
            "abTestID": "Unique identifier of the A/B test.",
            "name": "Name of the A/B test.",
            "status": "Current status of the A/B test (e.g. active, stopped, expired).",
            "variants": "List of variants with their index, traffic share, and per-variant results.",
            "createdAt": "Date the A/B test was created (ISO 8601).",
            "updatedAt": "Date the A/B test was last updated (ISO 8601).",
            "endAt": "Scheduled end date of the A/B test (ISO 8601).",
            "stoppedAt": "Date the A/B test was stopped, if it was stopped early (ISO 8601).",
            "configuration": "A/B test configuration, such as outlier and empty-search handling.",
            "decision": "Automatic decision on the test outcome, when available.",
        },
    },
}
