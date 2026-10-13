from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "resources": {
        "description": "CDN resources and their delivery domains, status, origins, and configuration.",
        "docs_url": "https://docs.gcore.com/api-reference/cdn/cdn-resources/get-cdn-resources-list",
        "columns": {
            "id": "Unique identifier of the CDN resource.",
            "cname": "Domain that delivers content through the CDN.",
            "created": "Time when the resource was created, in UTC.",
            "updated": "Time when the resource was last updated, in UTC.",
            "originGroup": "Identifier of the associated origin group.",
            "status": "Resource status: active, processed, suspended, or deleted.",
        },
    },
    "origin_groups": {
        "description": "Origin groups that supply content to CDN resources.",
        "docs_url": "https://docs.gcore.com/api-reference/cdn/origins/get-origin-groups-list",
        "columns": {
            "id": "Unique identifier of the origin group.",
            "name": "Name of the origin group.",
            "sources": "Origins that supply content to the group.",
            "has_related_resources": "Whether CDN resources use the origin group.",
        },
    },
    "ssl_certificates": {
        "description": "Certificates used for secure CDN delivery, including their domains and validity periods.",
        "docs_url": "https://docs.gcore.com/api-reference/cdn/ssl-certificates/get-ssl-certificates-list",
        "columns": {
            "id": "Unique identifier of the certificate.",
            "cert_issuer": "Certification authority that issued the certificate.",
            "cert_subject_cn": "Domain that the certificate secures.",
            "validity_not_after": "Time when the certificate expires, in UTC.",
            "validity_not_before": "Time when the certificate becomes valid, in UTC.",
        },
    },
    "cdn_requests": {
        "description": "Hourly counts of requests to CDN edge servers, grouped by resource.",
        "docs_url": "https://docs.gcore.com/api-reference/cdn/statistics/cdn-resource-statistics",
        "columns": {
            "resource_id": "Identifier of the CDN resource.",
            "timestamp": "Start of the hourly interval, in UTC.",
            "metric": "Metric name: requests.",
            "value": "Number of requests to edge servers during the interval.",
        },
    },
    "cdn_traffic": {
        "description": "Hourly traffic from CDN servers to clients, grouped by resource.",
        "docs_url": "https://docs.gcore.com/api-reference/cdn/statistics/cdn-resource-statistics",
        "columns": {
            "resource_id": "Identifier of the CDN resource.",
            "timestamp": "Start of the hourly interval, in UTC.",
            "metric": "Metric name: sent_bytes.",
            "value": "Bytes sent from CDN servers to clients during the interval.",
        },
    },
}
