from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Curated from the Jenkins remote access API (https://www.jenkins.io/doc/book/using/remote-access-api/).
# Keyed by the endpoint/schema name from settings.ENDPOINTS.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "jobs": {
        "description": "A job (project) in Jenkins, discovered by recursing into Folders and Multibranch Pipelines.",
        "docs_url": "https://www.jenkins.io/doc/book/using/remote-access-api/",
        "columns": {
            "id": "Stable identifier for the job — its API URL.",
            "name": "Short name of the job within its parent folder.",
            "fullName": "Fully qualified name including any parent folders (e.g. team/service/build).",
            "url": "Absolute URL of the job on the Jenkins instance.",
            "color": "Health/status indicator for the job's last build (e.g. blue, red, yellow; the _anime suffix means a build is running).",
            "_class": "Jenkins class of the job, distinguishing freestyle, pipeline, folder, and multibranch types.",
            "buildable": "Whether the job can currently be built (false for folders and disabled jobs).",
        },
    },
    "builds": {
        "description": "A single run of a job, carrying its result, duration, and start time.",
        "docs_url": "https://www.jenkins.io/doc/book/using/remote-access-api/",
        "columns": {
            "job_url": "Absolute URL of the job this build belongs to.",
            "created_at": "Build start time as an ISO 8601 datetime, derived from the epoch-millisecond timestamp.",
            "url": "Absolute URL of the build — globally unique and used as the primary key.",
            "number": "Sequential build number within its job (strictly monotonic per job).",
            "id": "Build id string (equal to the build number on modern Jenkins).",
            "result": "Outcome of the build (SUCCESS, FAILURE, UNSTABLE, ABORTED, or null while running).",
            "duration": "How long the build took, in milliseconds (0 while still running).",
            "estimatedDuration": "Jenkins' estimate of the build duration, in milliseconds.",
            "timestamp": "Build start time in epoch milliseconds.",
            "fullDisplayName": "Human-readable name including the job name and build number.",
            "displayName": "Display name of the build (usually #<number>).",
            "building": "Whether the build was still running when synced.",
            "queueId": "Identifier of the queue item this build came from.",
        },
    },
}
