from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "packages": {
        "description": "One row per configured package with its registry metadata: description, "
        "type, repository, download totals, favers, and GitHub stats.",
        "docs_url": "https://packagist.org/apidoc#get-package-data",
        "columns": {
            "name": "Full package name in vendor/package form. Globally unique on Packagist.",
            "description": "Short description of the package from its composer.json.",
            "time": "When the package was first published on Packagist (ISO 8601).",
            "maintainers": "Packagist users who maintain the package (name and avatar URL).",
            "type": "Composer package type, e.g. library, project, composer-plugin.",
            "repository": "URL of the package's source repository.",
            "downloads": "Download counters: total, monthly, and daily.",
            "favers": "Number of Packagist users who favorited the package.",
            "github_stars": "Star count of the package's GitHub repository, if hosted on GitHub.",
            "github_forks": "Fork count of the package's GitHub repository.",
            "github_watchers": "Watcher count of the package's GitHub repository.",
            "github_open_issues": "Open issue count of the package's GitHub repository.",
            "language": "Primary language of the repository as reported by GitHub.",
            "dependents": "Number of packages that depend on this package.",
            "suggesters": "Number of packages that suggest this package.",
        },
    },
    "versions": {
        "description": "One row per released version (and dev branch) of each configured package, "
        "with its dependencies, dist/source links, authors, and license.",
        "docs_url": "https://packagist.org/apidoc#get-package-data",
        "columns": {
            "package": "Full name (vendor/package) of the package this version belongs to.",
            "version": "Version string as published, e.g. 3.10.0 or dev-main.",
            "version_normalized": "Normalized version used by Composer for comparisons.",
            "name": "Full package name, repeated on every version object.",
            "description": "Description of the package at this version.",
            "time": "When this version was released (for dev branches: the last commit time).",
            "license": "SPDX license identifiers for this version.",
            "authors": "Authors listed in the version's composer.json.",
            "require": "Runtime dependencies as Composer package name to version constraint.",
            "require-dev": "Development dependencies of this version.",
            "dist": "Downloadable archive for this version (type, URL, reference).",
            "source": "Source repository pointer for this version (type, URL, reference).",
            "keywords": "Keywords declared in the version's composer.json.",
            "homepage": "Homepage URL declared in the version's composer.json.",
        },
    },
    "downloads": {
        "description": "Daily download statistics: one row per configured package per day, from "
        "the package download stats API.",
        "docs_url": "https://packagist.org/apidoc#get-package-stats",
        "columns": {
            "package": "Full name (vendor/package) of the package.",
            "date": "Day the downloads were counted (YYYY-MM-DD).",
            "downloads": "Number of Composer installs of the package on that day.",
        },
    },
    "security_advisories": {
        "description": "Security advisories affecting the configured packages, from the Packagist "
        "security advisories API.",
        "docs_url": "https://packagist.org/apidoc#list-security-advisories",
        "columns": {
            "advisoryId": "Packagist's unique identifier for the advisory (PKSA-...).",
            "packageName": "Full name (vendor/package) of the affected package.",
            "title": "Human-readable title of the advisory.",
            "link": "URL with details about the vulnerability.",
            "cve": "CVE identifier, when one has been assigned.",
            "affectedVersions": "Composer version constraint describing the vulnerable versions.",
            "severity": "Reported severity of the advisory, when available.",
            "reportedAt": "When the advisory was reported.",
            "source": "Primary advisory source, e.g. GitHub or FriendsOfPHP/security-advisories.",
            "sources": "All advisory sources and their remote identifiers.",
            "remoteId": "Identifier of the advisory in its source database.",
            "composerRepository": "Composer repository the advisory applies to.",
        },
    },
}
