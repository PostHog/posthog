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
    "artifact_statistics": {
        "description": "Download statistics for each artifact that has been downloaded at least once. Queried via AQL over the items domain with the statistic domain fields.",
        "docs_url": "https://docs.jfrog.com/artifactory/docs/aql-entities-fields-reference",
        "columns": {
            "repo": "Key of the repository the artifact lives in.",
            "path": "Folder path of the artifact within the repository.",
            "name": "File name of the artifact.",
            "created": "Time at which the artifact was first deployed.",
            "downloads": "Total number of downloads of the artifact.",
            "downloaded": "Last time the artifact was downloaded.",
            "downloaded_by": "Name of the last user to download the artifact.",
            "remote_downloads": "Total number of downloads through a smart remote repository proxying this repository.",
            "remote_downloaded": "Last time the artifact was downloaded through a smart remote repository proxy.",
            "remote_downloaded_by": "Name of the last user to download the artifact through a smart remote repository proxy.",
        },
    },
    "build_artifacts": {
        "description": "Artifacts produced by each build module, one row per artifact in a published build-info. Queried via AQL over the builds domain with module and artifact fields (requires an admin token).",
        "docs_url": "https://docs.jfrog.com/artifactory/docs/aql-entities-fields-reference",
        "columns": {
            "build_name": "Name of the build that produced the artifact.",
            "build_number": "Run number of the build that produced the artifact.",
            "build_created": "Time at which the build-info was published.",
            "module_name": "Name of the build module that produced the artifact.",
            "name": "Name of the artifact.",
            "type": "Type of the artifact.",
            "sha1": "SHA-1 checksum of the artifact.",
            "md5": "MD5 checksum of the artifact.",
        },
    },
    "build_dependencies": {
        "description": "Dependencies consumed by each build module, one row per dependency in a published build-info. Queried via AQL over the builds domain with module and dependency fields (requires an admin token).",
        "docs_url": "https://docs.jfrog.com/artifactory/docs/aql-entities-fields-reference",
        "columns": {
            "build_name": "Name of the build that used the dependency.",
            "build_number": "Run number of the build that used the dependency.",
            "build_created": "Time at which the build-info was published.",
            "module_name": "Name of the build module that used the dependency.",
            "name": "Name of the dependency.",
            "scope": "Scope of the dependency (e.g. compile, runtime, test).",
            "type": "Type of the dependency.",
            "sha1": "SHA-1 checksum of the dependency.",
            "md5": "MD5 checksum of the dependency.",
        },
    },
    "build_promotions": {
        "description": "Promotion history of builds: each time a build moved to a repository or changed status. Queried via AQL over the builds domain with promotion fields (requires an admin token).",
        "docs_url": "https://docs.jfrog.com/artifactory/docs/aql-entities-fields-reference",
        "columns": {
            "build_name": "Name of the promoted build.",
            "build_number": "Run number of the promoted build.",
            "build_created": "Time at which the build-info was published.",
            "created": "Time at which the build was promoted.",
            "created_by": "Artifactory user that promoted the build.",
            "status": "Status set by the promotion (e.g. staged, released).",
            "repo": "Repository the build was promoted to.",
            "comment": "Free-text comment about the promotion.",
            "user": "CI server user that promoted the build.",
        },
    },
    "xray_violations": {
        "description": "JFrog Xray security, license, and operational risk policy violations, one row per issue on a component under a watch.",
        "docs_url": "https://docs.jfrog.com/security/reference/get-violations",
        "columns": {
            "description": "Description of the violation.",
            "severity": "Severity of the violation (Critical, High, Medium, Low, Information, or Unknown).",
            "type": "Violation type: Security, License, or Operational_Risk.",
            "infected_components": "Components that triggered the violation.",
            "created": "Time at which the violation was created.",
            "watch_name": "Name of the Xray watch that raised the violation.",
            "issue_id": "Identifier of the Xray issue behind the violation.",
            "violation_details_url": "Xray API URL with the full details of the violation. Encodes the watch, issue, and component.",
            "impacted_artifacts": "Artifacts impacted by the violation.",
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
