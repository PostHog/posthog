from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the bunny.net Core API docs (https://docs.bunny.net/reference).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "pull_zones": {
        "description": "A bunny.net pull zone — the CDN configuration that caches and serves content from an origin.",
        "docs_url": "https://docs.bunny.net/reference/pullzonepublic_index",
        "columns": {
            "Id": "The unique ID of the pull zone.",
            "Name": "The name (and default hostname prefix) of the pull zone.",
            "OriginUrl": "The origin URL the pull zone pulls content from.",
            "Enabled": "Whether the pull zone is currently enabled.",
            "Suspended": "Whether the pull zone has been suspended.",
            "Hostnames": "The hostnames linked to this pull zone.",
            "StorageZoneId": "The ID of the storage zone used as the origin, if any.",
            "MonthlyBandwidthLimit": "The monthly bandwidth limit in bytes (0 = unlimited).",
            "MonthlyBandwidthUsed": "The amount of bandwidth used this month, in bytes.",
            "MonthlyCharges": "The total charges accrued for this pull zone this month.",
            "Type": "The pull zone tier (0 = Standard / Premium, 1 = Volume).",
            "UserId": "The ID of the account that owns the pull zone.",
        },
    },
    "storage_zones": {
        "description": "A bunny.net storage zone — replicated edge storage for files served via pull zones.",
        "docs_url": "https://docs.bunny.net/reference/storagezonepublic_index",
        "columns": {
            "Id": "The ID of the storage zone.",
            "Name": "The name of the storage zone.",
            "UserId": "The ID of the account that owns the storage zone.",
            "DateModified": "The date the storage zone was last modified.",
            "Deleted": "Whether the storage zone has been deleted.",
            "StorageUsed": "The amount of storage used, in bytes.",
            "FilesStored": "The number of files stored in the zone.",
            "Region": "The main storage region code of the zone.",
            "ReplicationRegions": "The regions the zone is replicated to.",
            "ZoneTier": "The storage tier (0 = Standard / HDD, 1 = Edge / SSD).",
        },
    },
    "dns_zones": {
        "description": "A bunny.net DNS zone — a managed domain and its DNS records.",
        "docs_url": "https://docs.bunny.net/reference/dnszonepublic_index",
        "columns": {
            "Id": "The unique ID of the DNS zone.",
            "Domain": "The domain name managed by this zone.",
            "Records": "The DNS records configured in the zone.",
            "DateCreated": "The date the DNS zone was created.",
            "DateModified": "The date the DNS zone was last modified.",
            "NameserversDetected": "Whether bunny.net's nameservers have been detected for the domain.",
            "CustomNameserversEnabled": "Whether custom nameservers are enabled.",
            "DnsSecEnabled": "Whether DNSSEC is enabled for the zone.",
            "LoggingEnabled": "Whether DNS query logging is enabled.",
        },
    },
    "video_libraries": {
        "description": "A bunny.net Stream video library — a container of videos with its own delivery and encoding settings.",
        "docs_url": "https://docs.bunny.net/reference/videolibrarypublic_index",
        "columns": {
            "Id": "The unique ID of the video library.",
            "Name": "The name of the video library.",
            "DateCreated": "The date the video library was created.",
            "VideoCount": "The number of videos in the library.",
            "TrafficUsage": "The amount of streaming traffic used, in bytes.",
            "StorageUsage": "The amount of storage used by the library, in bytes.",
            "ReplicationRegions": "The regions the library is replicated to.",
            "PullZoneId": "The ID of the pull zone used to deliver the library's content.",
            "StorageZoneId": "The ID of the storage zone backing the library.",
            "EnabledResolutions": "The video resolutions enabled for encoding.",
            "EncodingTier": "The encoding tier configured for the library.",
        },
    },
}
