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
    "conversion_rate": {
        "description": "Daily conversion rate for tracked searches on the index: conversion events "
        "divided by tracked searches.",
        "docs_url": "https://www.algolia.com/doc/rest-api/analytics/#tag/conversions/operation/getConversionRate",
        "columns": {
            "date": "Day the metrics cover, in YYYY-MM-DD format.",
            "rate": "Conversion rate for the day. Null when Algolia received no tracked searches.",
            "trackedSearchCount": "Number of searches that returned a query ID (click analytics enabled).",
            "conversionCount": "Number of conversion events attributed to searches on this day.",
        },
    },
    "add_to_cart_rate": {
        "description": "Daily add-to-cart rate for tracked searches on the index: add-to-cart events divided "
        "by tracked searches.",
        "docs_url": "https://www.algolia.com/doc/rest-api/analytics/#tag/conversions/operation/getAddToCartRate",
        "columns": {
            "date": "Day the metrics cover, in YYYY-MM-DD format.",
            "rate": "Add-to-cart rate for the day. Null when Algolia received no tracked searches.",
            "trackedSearchCount": "Number of searches that returned a query ID (click analytics enabled).",
            "addToCartCount": "Number of add-to-cart events attributed to searches on this day.",
        },
    },
    "purchase_rate": {
        "description": "Daily purchase rate for tracked searches on the index: purchase events divided by "
        "tracked searches.",
        "docs_url": "https://www.algolia.com/doc/rest-api/analytics/#tag/conversions/operation/getPurchaseRate",
        "columns": {
            "date": "Day the metrics cover, in YYYY-MM-DD format.",
            "rate": "Purchase rate for the day. Null when Algolia received no tracked searches.",
            "trackedSearchCount": "Number of searches that returned a query ID (click analytics enabled).",
            "purchaseCount": "Number of purchase events attributed to searches on this day.",
        },
    },
    "revenue": {
        "description": "Daily revenue attributed to searches on the index, from purchase events. Revenue is the "
        "event's price multiplied by quantity for each purchased object.",
        "docs_url": "https://www.algolia.com/doc/rest-api/analytics/#tag/conversions/operation/getRevenue",
        "columns": {
            "date": "Day the revenue covers, in YYYY-MM-DD format.",
            "currencies": "Revenue for the day keyed by currency code, each holding that currency's "
            "code and revenue amount.",
        },
    },
    "click_through_rate": {
        "description": "Daily click-through rate for tracked searches on the index: click events divided by "
        "tracked searches.",
        "docs_url": "https://www.algolia.com/doc/rest-api/analytics/#tag/clicks/operation/getClickThroughRate",
        "columns": {
            "date": "Day the metrics cover, in YYYY-MM-DD format.",
            "rate": "Click-through rate for the day. Null when there were no queries, 0 when there were "
            "queries but no click events.",
            "clickCount": "Number of clicks on search results on this day.",
            "trackedSearchCount": "Number of searches that returned a query ID (click analytics enabled).",
        },
    },
    "average_click_position": {
        "description": "Daily average position of clicked search results on the index. A value of 1 means users "
        "only clicked the first result.",
        "docs_url": "https://www.algolia.com/doc/rest-api/analytics/#tag/clicks/operation/getAverageClickPosition",
        "columns": {
            "date": "Day the metrics cover, in YYYY-MM-DD format.",
            "average": "Average position of the clicked results. Null until Algolia receives a click event.",
            "clickCount": "Number of clicks on search results on this day.",
        },
    },
    "users_count": {
        "description": "Daily count of unique users searching the index. Users are distinguished by their "
        "user token, or by IP address when no token is sent.",
        "docs_url": "https://www.algolia.com/doc/rest-api/analytics/#tag/analytics/operation/getUsersCount",
        "columns": {
            "date": "Day the count covers, in YYYY-MM-DD format.",
            "count": "Number of unique users on this day. Daily values do not sum to the period total, "
            "because a user active on several days counts once per day.",
        },
    },
    "top_filters": {
        "description": "Filter attributes used most often on the index over the recent period. Only attributes "
        "listed in the index's attributesForFaceting setting appear here.",
        "docs_url": "https://www.algolia.com/doc/rest-api/analytics/#tag/filters/operation/getTopFilterAttributes",
        "columns": {
            "attribute": "Name of the filter attribute.",
            "count": "Number of searches that applied a filter on this attribute.",
        },
    },
    "top_filter_values": {
        "description": "Filter values used most often for each filter attribute on the index over the recent "
        "period, one row per attribute/operator/value combination.",
        "docs_url": "https://www.algolia.com/doc/rest-api/analytics/#tag/filters/operation/getTopFilterForAttribute",
        "columns": {
            "attribute": "Name of the filter attribute the value belongs to.",
            "operator": "Character applying the filter, such as ':' for a facet filter or '>' for a numeric filter.",
            "value": "The filter value.",
            "count": "Number of searches that applied this attribute, operator and value together.",
        },
    },
    "top_countries": {
        "description": "Countries with the most searches on the index over the recent period.",
        "docs_url": "https://www.algolia.com/doc/rest-api/analytics/#tag/analytics/operation/getTopCountries",
        "columns": {
            "country": "Country code the searches came from.",
            "count": "Number of searches from this country.",
        },
    },
    "click_positions": {
        "description": "Clicks per position range in the index's search results over the recent period, so you "
        "can see how many clicks the first, second or tenth result received.",
        "docs_url": "https://www.algolia.com/doc/rest-api/analytics/#tag/clicks/operation/getClickPositions",
        "columns": {
            "position": "Range of result positions as [start, end]. Positions 11 and up are summed over "
            "the range, and -1 marks the end of the result list.",
            "clickCount": "Number of clicks on results in this position range.",
        },
    },
    "api_logs": {
        "description": "Log of the API requests made to the Algolia application. Algolia keeps the last seven days "
        "and up to 1,000 requests per server.",
        "docs_url": "https://www.algolia.com/doc/rest-api/search/get-logs",
        "columns": {
            "timestamp": "Date and time of the API request, in RFC 3339 format.",
            "method": "HTTP method of the request.",
            "answer_code": "HTTP status code of the response.",
            "query_body": "Request body, truncated to 1,000 characters.",
            "answer": "Response body, truncated to 1,000 characters.",
            "url": "URL of the API endpoint.",
            "ip": "IP address of the client that made the request.",
            "query_headers": "Request headers, with API keys obfuscated.",
            "sha1": "SHA1 signature of the log entry.",
            "nb_api_calls": "Number of API requests.",
            "processing_time_ms": "Processing time of the query in milliseconds, without network latency.",
            "index": "Index that the query targeted.",
            "query_params": "Query parameters sent with the request.",
            "query_nb_hits": "Number of search results (hits) that the query returned.",
            "inner_queries": "Queries that a multi-query request performed.",
            "cid": "Correlation ID of the request, also returned in its Correlation-ID response header.",
        },
    },
    "ingestion_runs": {
        "description": "Runs of the tasks of the Algolia Ingestion API (connectors), with status, outcome and progress.",
        "docs_url": "https://www.algolia.com/doc/rest-api/ingestion/list-runs",
        "columns": {
            "runID": "Universally unique identifier (UUID) of the task run.",
            "appID": "ID of the Algolia application.",
            "taskID": "Universally unique identifier (UUID) of the task that the run belongs to.",
            "status": "Task run status: created, started, finished or skipped.",
            "progress": "Number of events expected and received for the run.",
            "outcome": "Task run outcome: success or failure.",
            "failureThreshold": "Maximum percentage of failures accepted for the run to finish successfully.",
            "reason": "More information about the outcome of the run.",
            "reasonCode": "Code for the outcome of the run, described in `reason`.",
            "type": "Task run type: reindex, update, discover, validate or push.",
            "createdAt": "Date and time when the run was created, in RFC 3339 format.",
            "startedAt": "Date and time when the run started, in RFC 3339 format.",
            "finishedAt": "Date and time when the run finished, in RFC 3339 format.",
        },
    },
    "ingestion_run_events": {
        "description": "Events that describe the steps of each Ingestion API task run, such as fetches, record "
        "batches, transformations and log messages.",
        "docs_url": "https://www.algolia.com/doc/rest-api/ingestion/list-events",
        "columns": {
            "eventID": "Universally unique identifier (UUID) of the event.",
            "runID": "Universally unique identifier (UUID) of the task run that published the event.",
            "status": "Event status: created, started, retried, failed, succeeded or critical.",
            "type": "Event type: fetch, record, log or transform.",
            "batchSize": "Size of the extracted record batch.",
            "data": "Additional data about the event.",
            "publishedAt": "Date and time when the event was published, in RFC 3339 format.",
        },
    },
    "query_suggestions_configs": {
        "description": "Query Suggestions configurations of the Algolia application. Each one builds a Query "
        "Suggestions index from popular searches on its source indices.",
        "docs_url": "https://www.algolia.com/doc/rest-api/query-suggestions/get-all-configs",
        "columns": {
            "appID": "ID of the Algolia application.",
            "indexName": "Name of the Query Suggestions index.",
            "sourceIndices": "Indices whose searches and facet values generate the suggestions.",
            "languages": "Languages used for deduplicating singular and plural suggestions.",
            "exclude": "Words or regular expressions that exclude suggestions.",
            "enablePersonalization": "Whether to turn on personalized query suggestions.",
            "allowSpecialCharacters": "Whether to include suggestions with special characters.",
        },
    },
    "query_suggestions_logs": {
        "description": "Log entries from the latest build of each Query Suggestions index.",
        "docs_url": "https://www.algolia.com/doc/rest-api/query-suggestions/get-log-file",
        "columns": {
            "indexName": "Name of the Query Suggestions index that the entry belongs to.",
            "timestamp": "Date and time of the log entry, in RFC 3339 format.",
            "level": "Type of log entry: SKIP for a skipped query, INFO, or ERROR.",
            "message": "Details about the log entry.",
            "contextLevel": "Position of the suggestion in a hierarchy of records. Level 1 belongs to a previous "
            "suggestion with level 0.",
        },
    },
}
