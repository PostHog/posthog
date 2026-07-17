"""Canonical, documentation-sourced descriptions for JFrog Artifactory endpoints and columns.

Sourced from the official JFrog REST API and AQL references (https://jfrog.com/help/r/jfrog-rest-apis
and https://docs.jfrog.com/artifactory/docs/artifactory-query-language). Keyed by the endpoint names
in `settings.py` `JFROG_ARTIFACTORY_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "repositories": {
        "description": "A repository configured in Artifactory — local, remote, virtual, or federated — that stores or proxies packages.",
        "docs_url": "https://jfrog.com/help/r/jfrog-rest-apis/get-repositories",
        "columns": {
            "key": "Unique repository key (name).",
            "type": "Repository class: LOCAL, REMOTE, VIRTUAL, or FEDERATED.",
            "description": "Free-text description of the repository.",
            "url": "URL of the repository in Artifactory.",
            "packageType": "Package format the repository serves (e.g. Maven, Docker, npm, PyPI, Generic).",
        },
    },
    "artifacts": {
        "description": "A file (artifact) stored in an Artifactory repository, with its coordinates, checksums, and timestamps. Queried via AQL over the items domain.",
        "docs_url": "https://docs.jfrog.com/artifactory/docs/aql-entities-fields-reference",
        "columns": {
            "repo": "Key of the repository the artifact lives in.",
            "path": "Folder path of the artifact within the repository.",
            "name": "File name of the artifact.",
            "type": "Item type; artifact rows are files.",
            "size": "Size of the artifact in bytes.",
            "created": "Time at which the artifact was first deployed.",
            "created_by": "User that deployed the artifact.",
            "modified": "Time at which the artifact was last modified.",
            "modified_by": "User that last modified the artifact.",
            "updated": "Time at which the artifact's metadata was last updated.",
            "sha256": "SHA-256 checksum of the artifact.",
            "actual_sha1": "SHA-1 checksum of the artifact.",
            "actual_md5": "MD5 checksum of the artifact.",
        },
    },
    "builds": {
        "description": "Build-info records published to Artifactory by CI servers, one row per build run. Queried via AQL over the builds domain (requires an admin token).",
        "docs_url": "https://docs.jfrog.com/artifactory/docs/aql-entities-fields-reference",
        "columns": {
            "name": "Name of the build.",
            "number": "Run number of the build.",
            "created": "Time at which the build-info was published.",
            "created_by": "User that published the build-info.",
            "modified": "Time at which the build-info was last modified.",
            "modified_by": "User that last modified the build-info.",
            "url": "URL of the build run on the CI server.",
        },
    },
    "storage_summary": {
        "description": "Point-in-time storage summary per repository — file counts and used space — from the storageinfo API (requires an admin token).",
        "docs_url": "https://jfrog.com/help/r/jfrog-rest-apis/get-storage-summary-info",
        "columns": {
            "repoKey": "Key of the repository the summary row describes.",
            "repoType": "Repository class: LOCAL, REMOTE, VIRTUAL, FEDERATED, or NA for totals.",
            "foldersCount": "Number of folders in the repository.",
            "filesCount": "Number of files in the repository.",
            "usedSpace": "Human-readable used storage space.",
            "usedSpaceInBytes": "Used storage space in bytes.",
            "itemsCount": "Total number of items (files and folders) in the repository.",
            "packageType": "Package format the repository serves.",
            "projectKey": "Key of the JFrog project the repository belongs to, if any.",
            "percentage": "Share of total instance storage used by the repository.",
        },
    },
}
