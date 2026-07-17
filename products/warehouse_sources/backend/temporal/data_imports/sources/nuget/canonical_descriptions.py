from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "packages": {
        "description": (
            "One row per tracked package from the NuGet search service, carrying package-level metadata "
            "and the all-time total download count as of the sync."
        ),
        "docs_url": "https://learn.microsoft.com/en-us/nuget/api/search-query-service-resource",
        "columns": {
            "id": "The package ID, the case-insensitive unique identifier of the package.",
            "version": "The latest full SemVer 2.0.0 version of the package (including prereleases).",
            "title": "The display title of the package's latest version.",
            "description": "The description of the package's latest version.",
            "summary": "The summary of the package's latest version.",
            "authors": "The authors of the package, as declared in the package manifest.",
            "owners": "The nuget.org accounts that own the package.",
            "tags": "The tags of the package's latest version.",
            "iconUrl": "URL of the package's icon.",
            "licenseUrl": "URL of the package's license.",
            "projectUrl": "URL of the package's project homepage.",
            "registration": "URL of the package's registration index.",
            "totalDownloads": "The all-time total number of downloads across every version of the package.",
            "verified": "Whether the package ID is verified (owned under a reserved ID prefix).",
            "packageTypes": "The package types declared by the latest version (e.g. Dependency, DotnetTool).",
            "vulnerabilities": "Known vulnerabilities affecting the package's latest version.",
        },
    },
    "package_versions": {
        "description": (
            "One row per published version of each tracked package from the NuGet registration index, "
            "with the per-version download count merged in from the search service."
        ),
        "docs_url": "https://learn.microsoft.com/en-us/nuget/api/registration-base-url-resource",
        "columns": {
            "id": "The package ID this version belongs to.",
            "version": "The full SemVer 2.0.0 version string of this package version.",
            "published": (
                "When this version was published. NuGet rewrites this to the year 1900 while a version is unlisted."
            ),
            "listed": "Whether this version is listed (visible in search results and version lists).",
            "downloads": "The all-time number of downloads of this specific version, from the search service.",
            "authors": "The authors of this version, as declared in the package manifest.",
            "description": "The description of this version.",
            "summary": "The summary of this version.",
            "title": "The display title of this version.",
            "tags": "The tags of this version.",
            "iconUrl": "URL of this version's icon.",
            "licenseUrl": "URL of this version's license.",
            "licenseExpression": "The SPDX license expression of this version, when declared.",
            "projectUrl": "URL of this version's project homepage.",
            "packageContent": "URL of the .nupkg file for this version.",
            "minClientVersion": "The minimum NuGet client version required to install this version.",
            "requireLicenseAcceptance": "Whether installing this version requires accepting the license.",
            "language": "The language declared in the package manifest.",
            "dependencyGroups": "The dependencies of this version, grouped by target framework.",
            "deprecation": "Deprecation metadata for this version, when it has been deprecated.",
            "vulnerabilities": "Known vulnerabilities affecting this version.",
        },
    },
    "catalog_events": {
        "description": (
            "Publish, edit, and delete events for the tracked packages, from the append-only NuGet "
            "catalog. One row per catalog leaf (event)."
        ),
        "docs_url": "https://learn.microsoft.com/en-us/nuget/api/catalog-resource",
        "columns": {
            "catalog_leaf_url": "URL of the catalog leaf document describing this event. Unique per event.",
            "event_type": (
                "The event type: nuget:PackageDetails for a package version being published or edited, "
                "nuget:PackageDelete for a version being hard-deleted."
            ),
            "commit_id": "ID of the catalog commit this event belongs to.",
            "commit_timestamp": "When the event was committed to the catalog. The incremental sync cursor.",
            "package_id": "The package ID the event applies to.",
            "package_version": "The package version the event applies to.",
        },
    },
}
