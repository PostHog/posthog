"""Canonical, documentation-sourced descriptions for Skyvern endpoints and columns.

Sourced from the official Skyvern API reference (https://docs.skyvern.com/api-reference). Keyed by the
endpoint names in `settings.py` `SKYVERN_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Skyvern table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workflows": {
        "description": "A Skyvern workflow definition — a reusable, multi-step browser-automation agent.",
        "docs_url": "https://docs.skyvern.com/api-reference/api-reference/workflows",
        "columns": {
            "workflow_id": "Identifier of this specific workflow version.",
            "workflow_permanent_id": "Stable identifier that persists across all versions of the workflow.",
            "organization_id": "Identifier of the organization that owns the workflow.",
            "title": "Human-readable title of the workflow.",
            "description": "Description of what the workflow does.",
            "version": "Version number of this workflow definition.",
            "is_saved_task": "Whether this workflow was created from a saved task.",
            "is_template": "Whether this workflow is a reusable template.",
            "workflow_definition": "The full block/parameter definition of the workflow.",
            "status": "Publish status of the workflow (e.g. published, draft).",
            "proxy_location": "Geographic proxy location runs of this workflow use.",
            "webhook_callback_url": "URL Skyvern calls back when a run of this workflow completes.",
            "folder_id": "Identifier of the folder the workflow lives in, if any.",
            "created_at": "Time at which the workflow version was created.",
            "modified_at": "Time at which the workflow version was last modified.",
            "deleted_at": "Time at which the workflow was deleted, if it has been.",
        },
    },
    "runs": {
        "description": "A single run of a Skyvern task or workflow, with status, credits used, and timing.",
        "docs_url": "https://docs.skyvern.com/api-reference/api-reference/workflows/get-workflow-runs-by-id",
        "columns": {
            "workflow_run_id": "Unique identifier for the run.",
            "workflow_id": "Identifier of the workflow version that was run.",
            "workflow_permanent_id": "Stable identifier of the workflow that was run.",
            "organization_id": "Identifier of the organization that owns the run.",
            "workflow_title": "Title of the workflow that was run.",
            "status": "Current run status (created, queued, running, completed, failed, terminated, canceled, timed_out, paused).",
            "failure_reason": "Human-readable reason the run failed, if it did.",
            "failure_category": "Categorized failure information for the run.",
            "trigger_type": "What triggered the run (e.g. api, schedule, ui).",
            "workflow_schedule_id": "Identifier of the schedule that triggered the run, if any.",
            "credits_used": "Number of Skyvern credits the run consumed.",
            "cached_credits_used": "Number of credits served from cache for the run.",
            "browser_session_id": "Identifier of the browser session the run used.",
            "browser_profile_id": "Identifier of the browser profile the run used.",
            "parent_workflow_run_id": "Identifier of the parent run, for nested workflow runs.",
            "webhook_callback_url": "URL Skyvern called back when the run completed.",
            "queued_at": "Time at which the run was queued.",
            "started_at": "Time at which the run started executing.",
            "finished_at": "Time at which the run finished.",
            "created_at": "Time at which the run was created.",
            "modified_at": "Time at which the run was last modified.",
        },
    },
    "schedules": {
        "description": "A cron schedule that triggers a Skyvern workflow to run automatically.",
        "docs_url": "https://docs.skyvern.com/api-reference/api-reference/schedules",
        "columns": {
            "workflow_schedule_id": "Unique identifier for the schedule.",
            "organization_id": "Identifier of the organization that owns the schedule.",
            "workflow_permanent_id": "Stable identifier of the workflow the schedule triggers.",
            "workflow_title": "Title of the workflow the schedule triggers.",
            "cron_expression": "Cron expression defining when the schedule fires.",
            "timezone": "Timezone the cron expression is evaluated in.",
            "enabled": "Whether the schedule is currently active.",
            "parameters": "Parameter values passed to each scheduled run.",
            "name": "Name of the schedule.",
            "description": "Description of the schedule.",
            "next_run": "Time at which the schedule will next fire.",
            "created_at": "Time at which the schedule was created.",
            "modified_at": "Time at which the schedule was last modified.",
        },
    },
    "browser_profiles": {
        "description": "A persisted browser profile (cookies and local storage) reusable across runs.",
        "docs_url": "https://docs.skyvern.com/api-reference/api-reference/browser-profiles",
        "columns": {
            "browser_profile_id": "Unique identifier for the browser profile.",
            "organization_id": "Identifier of the organization that owns the profile.",
            "name": "Name of the browser profile.",
            "description": "Description of the browser profile.",
            "is_managed": "Whether the profile is managed by Skyvern.",
            "proxy_location": "Geographic proxy location the profile uses.",
            "workflow_permanent_id": "Stable identifier of the workflow the profile is tied to, if any.",
            "created_at": "Time at which the profile was created.",
            "modified_at": "Time at which the profile was last modified.",
            "deleted_at": "Time at which the profile was deleted, if it has been.",
        },
    },
    "credentials": {
        "description": "Metadata for a stored credential used by workflows. Secret values are never returned.",
        "docs_url": "https://docs.skyvern.com/api-reference/api-reference/credentials",
        "columns": {
            "credential_id": "Unique identifier for the credential.",
            "name": "Name of the credential.",
            "credential_type": "Type of credential (e.g. password, credit_card).",
            "vault_type": "The vault backing the credential.",
            "browser_profile_id": "Identifier of the browser profile the credential is tied to, if any.",
            "tested_url": "URL the credential was last tested against.",
            "folder_id": "Identifier of the folder the credential lives in, if any.",
        },
    },
}
