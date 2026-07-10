from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS = "https://www.koyeb.com/docs/api"

# Curated from the Koyeb public API reference. The Swagger spec ships almost no field-level
# descriptions, so only well-known, stable columns are documented here; anything omitted falls back
# to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "apps": {
        "description": "Koyeb apps — the top-level grouping that owns one or more services and their public domains.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the app.",
            "name": "Human-readable app name, unique within the organization.",
            "organization_id": "Identifier of the organization that owns the app.",
            "status": "Current lifecycle status of the app.",
            "created_at": "Time the app was created.",
            "updated_at": "Time the app was last updated.",
        },
    },
    "services": {
        "description": "Services within an app — each service is a deployable workload (web, worker, or database).",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the service.",
            "name": "Service name, unique within the app.",
            "app_id": "Identifier of the app this service belongs to.",
            "type": "Service type (e.g. web or worker).",
            "status": "Current lifecycle status of the service.",
            "active_deployment_id": "Deployment currently serving traffic for the service.",
            "latest_deployment_id": "Most recently created deployment for the service.",
            "created_at": "Time the service was created.",
            "updated_at": "Time the service was last updated.",
        },
    },
    "deployments": {
        "description": "Deployments — a specific versioned rollout of a service, built and released across regions.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the deployment.",
            "service_id": "Identifier of the service this deployment belongs to.",
            "app_id": "Identifier of the app this deployment belongs to.",
            "status": "Current status of the deployment.",
            "created_at": "Time the deployment was created.",
            "succeeded_at": "Time the deployment finished successfully, if it did.",
            "terminated_at": "Time the deployment was terminated, if it was.",
        },
    },
    "regional_deployments": {
        "description": "Per-region rollouts of a deployment, tracking status in each datacenter region.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the regional deployment.",
            "region": "Region this deployment runs in.",
            "status": "Current status of the regional deployment.",
            "created_at": "Time the regional deployment was created.",
        },
    },
    "instances": {
        "description": "Running instances (replicas) of a service, one row per instance in a region.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the instance.",
            "service_id": "Identifier of the service this instance runs.",
            "deployment_id": "Identifier of the deployment this instance was created from.",
            "region": "Region the instance runs in.",
            "type": "Instance type / size.",
            "status": "Current status of the instance.",
            "created_at": "Time the instance was created.",
        },
    },
    "domains": {
        "description": "Custom and Koyeb-provided domains attached to apps, with verification status.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the domain.",
            "name": "The domain name.",
            "app_id": "Identifier of the app the domain is attached to.",
            "status": "Verification / attachment status of the domain.",
            "verified_at": "Time the domain was verified, if it has been.",
            "created_at": "Time the domain was created.",
        },
    },
    "secrets": {
        "description": "Organization secrets (environment values and registry credentials). Secret values are not returned by the API.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the secret.",
            "name": "Secret name, unique within the organization.",
            "type": "Secret type (e.g. simple or a registry credential).",
            "created_at": "Time the secret was created.",
        },
    },
    "volumes": {
        "description": "Persistent volumes that can be attached to services for durable storage.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the volume.",
            "name": "Volume name.",
            "region": "Region the volume lives in.",
            "cur_size": "Current size of the volume.",
            "max_size": "Maximum size the volume can grow to.",
            "status": "Current status of the volume.",
            "created_at": "Time the volume was created.",
        },
    },
    "snapshots": {
        "description": "Volume snapshots used to back up and restore persistent volumes.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the snapshot.",
            "name": "Snapshot name.",
            "parent_volume_id": "Volume this snapshot was taken from.",
            "region": "Region the snapshot lives in.",
            "status": "Current status of the snapshot.",
            "created_at": "Time the snapshot was created.",
        },
    },
    "instance_snapshots": {
        "description": "Instance snapshots capturing the state of an instance for later restore.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the instance snapshot.",
            "service_id": "Service the snapshot relates to.",
            "instance_id": "Instance the snapshot was taken from.",
            "status": "Current status of the instance snapshot.",
            "created_at": "Time the instance snapshot was created.",
        },
    },
    "organization_members": {
        "description": "Members of the organization the API token belongs to, with their role and status.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the membership.",
            "user_id": "Identifier of the member's user account.",
            "role": "Role the member holds in the organization.",
            "status": "Membership status.",
            "joined_at": "Time the member joined the organization.",
        },
    },
    "app_events": {
        "description": "Append-only event log for apps (created, updated, deleted, and similar lifecycle events).",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the event.",
            "app_id": "App the event relates to.",
            "type": "Event type.",
            "message": "Human-readable event message.",
            "when": "Time the event occurred.",
        },
    },
    "service_events": {
        "description": "Append-only event log for services.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the event.",
            "service_id": "Service the event relates to.",
            "type": "Event type.",
            "message": "Human-readable event message.",
            "when": "Time the event occurred.",
        },
    },
    "deployment_events": {
        "description": "Append-only event log for deployments.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the event.",
            "deployment_id": "Deployment the event relates to.",
            "type": "Event type.",
            "message": "Human-readable event message.",
            "when": "Time the event occurred.",
        },
    },
    "instance_events": {
        "description": "Append-only event log for instances.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the event.",
            "instance_id": "Instance the event relates to.",
            "type": "Event type.",
            "message": "Human-readable event message.",
            "when": "Time the event occurred.",
        },
    },
    "activities": {
        "description": "Append-only audit log of actions taken in the organization, with actor, object, and verb.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the activity.",
            "verb": "Action that was performed.",
            "created_at": "Time the activity was recorded.",
        },
    },
    "usage_details": {
        "description": "Per-instance usage and billing detail records, windowed by time — used for cost analysis.",
        "docs_url": _DOCS,
        "columns": {
            "instance_id": "Instance the usage record is for.",
            "deployment_id": "Deployment the instance belonged to.",
            "service_id": "Service the usage is attributed to.",
            "region": "Region the usage was incurred in.",
            "instance_type": "Instance type / size being billed.",
            "duration_seconds": "Duration the instance ran, in seconds.",
            "started_at": "Start of the usage window.",
            "terminated_at": "End of the usage window.",
        },
    },
}
