from products.warehouse_sources.sources.sdk import CanonicalDescriptions

_DOWNLOAD_COUNTS_DOCS = "https://github.com/npm/registry/blob/master/docs/download-counts.md"
_REGISTRY_API_DOCS = "https://github.com/npm/registry/blob/master/docs/REGISTRY-API.md"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Downloads": {
        "description": "Daily download counts per configured package, from the npm downloads-counts API "
        "(api.npmjs.org).",
        "docs_url": _DOWNLOAD_COUNTS_DOCS,
        "columns": {
            "package": "Name of the npm package (injected by the connector; not returned by the endpoint).",
            "day": "Day the downloads were counted (UTC); used as the partition key.",
            "downloads": "Number of package downloads (tarball fetches) on that day.",
        },
    },
    "Versions": {
        "description": "Published version metadata across every configured package, one row per version, "
        "from the npm registry's package document (registry.npmjs.org/{package}).",
        "docs_url": _REGISTRY_API_DOCS,
        "columns": {
            "package": "Name of the npm package (injected by the connector; not returned per-version).",
            "version": "Version string of this release (semver).",
            "published_at": "When this version was published, from the document's `time` map; used as the "
            "partition key.",
            "is_latest": "Whether this version is the package's current `latest` dist-tag.",
            "deprecated": "Deprecation message set on this version, if the maintainer deprecated it.",
            "license": "License declared for this version (SPDX identifier or free text).",
            "description": "Package description at the time this version was published.",
            "tarball": "URL to download this version's packaged tarball.",
            "shasum": "SHA-1 checksum of the packaged tarball.",
            "integrity": "Subresource Integrity (SRI) hash of the packaged tarball.",
            "node_engine": "Value of the `engines.node` manifest field, if declared, constraining compatible "
            "Node.js versions.",
        },
    },
    "VersionDownloads": {
        "description": "Download counts per published version over the last 7 days, per configured package, "
        "from the npm downloads-counts API (api.npmjs.org/versions/{package}/last-week). Each sync replaces "
        "the table with the current rolling 7-day window.",
        "docs_url": _DOWNLOAD_COUNTS_DOCS,
        "columns": {
            "package": "Name of the npm package (injected by the connector).",
            "version": "Version string of the release; joins to the Versions table on package and version.",
            "downloads": "Number of downloads of this version over the last 7 available days.",
        },
    },
    "Packages": {
        "description": "Current summary of each configured package, one row per package, from the npm registry "
        "search API (registry.npmjs.org/-/v1/search). Each sync replaces the table with the current snapshot.",
        "docs_url": _REGISTRY_API_DOCS,
        "columns": {
            "package": "Name of the npm package (injected by the connector).",
            "version": "Latest published version of the package.",
            "description": "Package description from its latest version.",
            "keywords": "Keywords declared in the package manifest.",
            "license": "License declared by the latest version.",
            "published_at": "When the latest version was published.",
            "publisher": "npm username that published the latest version.",
            "maintainers": "npm usernames of the package maintainers.",
            "homepage": "Homepage URL declared by the package.",
            "repository": "Source repository URL declared by the package.",
            "bugs": "Issue tracker URL declared by the package.",
            "npm_url": "URL of the package page on npmjs.com.",
            "weekly_downloads": "Downloads over the last 7 days, as reported by the search index.",
            "monthly_downloads": "Downloads over the last 30 days, as reported by the search index.",
            "dependents": "Number of packages in the registry that depend on this package.",
            "search_score": "Relevance score of the package for a search on its own name.",
            "score_final": "Overall search ranking score.",
            "score_quality": "Quality component of the search ranking score.",
            "score_popularity": "Popularity component of the search ranking score.",
            "score_maintenance": "Maintenance component of the search ranking score.",
            "insecure": "Whether the search index flags the package as having known security issues (1) or not (0).",
            "updated_at": "When the search index last updated this package's entry.",
        },
    },
}
