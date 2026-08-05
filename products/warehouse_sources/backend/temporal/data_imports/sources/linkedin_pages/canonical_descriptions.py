from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_ORGANIZATION_COLUMNS = {
    "organization": "URN of the LinkedIn page the row was fetched for, e.g. `urn:li:organization:1234`.",
    "organization_id": "Numeric ID from the organization URN.",
    "date": "Day the statistics cover, derived from the element's `timeRange.start` (UTC).",
    "timeRange": "Epoch-millisecond range the element covers. `start` is the beginning of the day, `end` the exclusive edge.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "organizations": {
        "description": "A LinkedIn company page (organization) the authorized member administers.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/community-management/organizations/organization-lookup-api",
        "columns": {
            "id": "Unique numeric ID of the organization.",
            "urn": "Full URN of the organization, e.g. `urn:li:organization:1234`.",
            "localizedName": "Organization name in the page's primary locale.",
            "vanityName": "Public URL slug of the page, e.g. `posthog` in linkedin.com/company/posthog.",
            "localizedWebsite": "Website URL shown on the page, in its primary locale.",
            "localizedDescription": "Page description in its primary locale.",
            "organizationStatus": "Lifecycle status of the page, e.g. OPERATING.",
            "organizationType": "Type of organization, e.g. PUBLIC_COMPANY or NON_PROFIT.",
            "staffCountRange": "Bucketed employee-count range reported on the page.",
            "primaryOrganizationType": "Whether the entity is a parent organization, a brand, or none.",
            "parentRelationship": "Link to the parent organization when this page is a showcase or brand page.",
            "locations": "Addresses associated with the page.",
            "industries": "Industry URNs the page is classified under.",
            "specialties": "Specialty tags listed on the page.",
        },
    },
    "page_statistics": {
        "description": "Daily views and clicks on the sections of a LinkedIn company page.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/community-management/organizations/page-statistics",
        "columns": {
            **_ORGANIZATION_COLUMNS,
            "totalPageStatistics": "Views and clicks aggregated across every section of the page for the day.",
            "pageStatisticsBySeniority": "Page views broken down by the seniority of the viewing member.",
            "pageStatisticsByIndustry": "Page views broken down by the industry of the viewing member.",
            "pageStatisticsByFunction": "Page views broken down by the job function of the viewing member.",
            "pageStatisticsByStaffCountRange": "Page views broken down by the company size of the viewing member.",
            "pageStatisticsByCountry": "Page views broken down by the country of the viewing member.",
            "pageStatisticsByRegion": "Page views broken down by the region of the viewing member.",
        },
    },
    "follower_statistics": {
        "description": "Daily follower gains for a LinkedIn company page, split by how the follow was acquired.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/community-management/organizations/follower-statistics",
        "columns": {
            **_ORGANIZATION_COLUMNS,
            "organizationalEntity": "URN of the page the follower statistics belong to.",
            "followerGains": "Followers gained during the day, split into organic and paid.",
        },
    },
    "share_statistics": {
        "description": "Daily engagement totals across all posts published by a LinkedIn company page.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/share-statistics",
        "columns": {
            **_ORGANIZATION_COLUMNS,
            "organizationalEntity": "URN of the page the share statistics belong to.",
            "totalShareStatistics": "Impressions, clicks, likes, comments, shares and engagement rate for the day.",
        },
    },
    "posts": {
        "description": "Posts published by a LinkedIn company page.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api",
        "columns": {
            "id": "URN of the post, e.g. `urn:li:share:1234` or `urn:li:ugcPost:1234`.",
            "organization": "URN of the page the post was fetched for.",
            "organization_id": "Numeric ID from the organization URN.",
            "author": "URN of the member or organization that authored the post.",
            "commentary": "Text body of the post.",
            "content": "Media attached to the post — article, image, video, poll or document.",
            "created_at": "Creation time of the post, derived from `createdAt` (UTC).",
            "createdAt": "Creation time of the post, in epoch milliseconds.",
            "lastModifiedAt": "Time the post was last modified, in epoch milliseconds.",
            "publishedAt": "Time the post was published, in epoch milliseconds.",
            "lifecycleState": "State of the post, e.g. PUBLISHED, DRAFT or PUBLISH_FAILED.",
            "visibility": "Audience of the post, e.g. PUBLIC or LOGGED_IN.",
            "distribution": "How the post is distributed across LinkedIn feeds and third-party targets.",
            "isReshareDisabledByAuthor": "Whether the author blocked resharing of the post.",
            "reshareContext": "Original post this one reshares, when applicable.",
        },
    },
}
