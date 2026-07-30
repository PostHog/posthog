from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "repositories": {
        "description": "A repository configured on the Nexus instance — hosted, proxy, or group — for a package format such as Maven, npm, Docker, or PyPI.",
        "docs_url": "https://help.sonatype.com/en/repositories-api.html",
        "columns": {
            "name": "Unique name of the repository on the instance.",
            "format": "Package format the repository serves (e.g. maven2, npm, docker, pypi, nuget).",
            "type": "Repository type: hosted (stores uploads), proxy (caches a remote), or group (aggregates other repositories).",
            "url": "Base URL clients use to access the repository's content.",
            "attributes": "Format- and type-specific settings, such as a proxy repository's remote URL.",
        },
    },
    "components": {
        "description": "A versioned package (e.g. a Maven artifact, npm package, or Docker image) stored in a hosted or proxy repository. Group repositories are excluded to avoid double-counting their members' components.",
        "docs_url": "https://help.sonatype.com/en/components-api.html",
        "columns": {
            "id": "Opaque identifier of the component within the instance.",
            "repository": "Name of the repository the component lives in.",
            "format": "Package format of the component (e.g. maven2, npm, docker, pypi).",
            "group": "Component namespace, such as a Maven groupId. Null for formats without one.",
            "name": "Component name, such as a Maven artifactId or npm package name.",
            "version": "Component version.",
            "assets": "The component's files, each with path, download URL, checksums, and size.",
            "tags": "Tags applied to the component (Nexus Repository Pro).",
        },
    },
    "assets": {
        "description": "An individual file stored in a hosted or proxy repository, such as a .jar, .tgz, or Docker layer, with its checksums, size, and download metadata. Group repositories are excluded to avoid double-counting their members' assets.",
        "docs_url": "https://help.sonatype.com/en/assets-api.html",
        "columns": {
            "id": "Opaque identifier of the asset within the instance.",
            "repository": "Name of the repository the asset lives in.",
            "format": "Package format of the asset (e.g. maven2, npm, docker, pypi).",
            "path": "Path of the asset within the repository.",
            "downloadUrl": "URL to download the asset's content.",
            "contentType": "MIME type of the asset's content.",
            "fileSize": "Size of the asset in bytes.",
            "checksum": "Checksums of the asset's content (md5, sha1, sha256, sha512 where available).",
            "blobCreated": "When the asset's blob was created. Can be null for blobs created before the instance recorded it.",
            "lastModified": "When the asset was last modified.",
            "lastDownloaded": "When the asset was last downloaded by a client.",
            "uploader": "Username that uploaded the asset.",
            "uploaderIp": "IP address the asset was uploaded from.",
        },
    },
    "tasks": {
        "description": "A scheduled or manually triggered maintenance task on the Nexus instance, such as blob store compaction or repository cleanup, with its schedule and last run state.",
        "docs_url": "https://help.sonatype.com/en/tasks-api.html",
        "columns": {
            "id": "Unique identifier of the task.",
            "name": "Display name of the task.",
            "type": "Task type identifier (e.g. blobstore.compact, repository.cleanup).",
            "message": "Status message from the task's most recent activity.",
            "currentState": "Current state of the task (e.g. WAITING, RUNNING).",
            "lastRunResult": "Result of the task's last run (e.g. OK, FAILED).",
            "nextRun": "When the task is next scheduled to run.",
            "lastRun": "When the task last ran.",
        },
    },
}
