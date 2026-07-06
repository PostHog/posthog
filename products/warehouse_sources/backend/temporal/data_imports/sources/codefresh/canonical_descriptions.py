from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions are taken from the Codefresh public API reference (https://g.codefresh.io/api/).
# Codefresh is a fixed-schema SaaS source, so the table/column meanings are the same for every
# account and worth documenting once here instead of re-deriving them per team via the LLM.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "A Codefresh project — a logical grouping of pipelines, with shared variables and tags.",
        "docs_url": "https://g.codefresh.io/api/",
        "columns": {
            "id": "Unique identifier of the project.",
            "projectName": "Human-readable name of the project.",
            "accountId": "Identifier of the Codefresh account the project belongs to.",
            "tags": "Free-form tags applied to the project.",
            "variables": "Project-level shared variables available to its pipelines.",
            "pipelinesNumber": "Number of pipelines that belong to the project.",
            "updatedAt": "Timestamp of the last update to the project.",
            "favorite": "Whether the project is marked as a favorite.",
        },
    },
    "pipelines": {
        "description": "A Codefresh pipeline definition. The pipeline's `metadata` fields (id, name, project, …) are lifted to the row's top level; the build specification stays under `spec`.",
        "docs_url": "https://g.codefresh.io/api/",
        "columns": {
            "id": "Unique identifier of the pipeline (from metadata).",
            "name": "Name of the pipeline (from metadata).",
            "project": "Name of the project the pipeline belongs to.",
            "projectId": "Identifier of the project the pipeline belongs to.",
            "spec": "Pipeline specification: triggers, steps, and runtime configuration.",
        },
    },
    "builds": {
        "description": "A pipeline build (workflow execution), including its status, trigger, and source commit.",
        "docs_url": "https://g.codefresh.io/api/",
        "columns": {
            "id": "Unique identifier of the build.",
            "created": "Timestamp the build was created.",
            "finished": "Timestamp the build finished, if it has completed.",
            "status": "Final or current status of the build (e.g. success, error, running, terminated).",
            "pipelineName": "Name of the pipeline that produced the build.",
            "project": "Name of the project the build belongs to.",
            "trigger": "How the build was triggered (e.g. build, promote).",
            "triggeredBy": "User or system that triggered the build.",
            "repoOwner": "Owner of the source repository.",
            "repoName": "Name of the source repository.",
            "branchName": "Source branch the build ran against.",
            "revision": "Commit revision the build ran against.",
            "commitMessage": "Commit message of the source revision.",
        },
    },
    "images": {
        "description": "A container image produced and tracked by Codefresh builds.",
        "docs_url": "https://g.codefresh.io/api/",
        "columns": {
            "id": "Unique identifier of the image.",
            "created": "Timestamp the image was created.",
            "imageName": "Name of the image.",
            "tags": "Tags applied to the image.",
            "branch": "Source branch the image was built from.",
            "sha": "Image SHA digest.",
            "commit": "Source commit the image was built from.",
            "size": "Size of the image.",
            "internalImageId": "Codefresh-internal identifier of the image.",
        },
    },
    "triggers": {
        "description": "A Hermes trigger linking a trigger-event to the pipeline it fires.",
        "docs_url": "https://g.codefresh.io/api/",
        "columns": {
            "event": "Identifier of the trigger-event.",
            "pipeline": "Identifier of the pipeline the event triggers.",
            "filters": "Filters that further constrain when the trigger fires.",
        },
    },
    "step_types": {
        "description": "A Codefresh typed step (plugin) available to pipelines, from the public and account step-type catalog.",
        "docs_url": "https://g.codefresh.io/api/",
        "columns": {
            "id": "Unique identifier of the step type.",
        },
    },
}
