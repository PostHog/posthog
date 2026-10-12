from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

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
}
