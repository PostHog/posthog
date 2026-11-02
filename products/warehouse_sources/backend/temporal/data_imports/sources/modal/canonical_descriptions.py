from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    name: {
        "description": f"{resolution} workspace costs by Modal object and environment.",
        "docs_url": "https://modal.com/docs/sdk/py/latest/Workspace#billingreport",
        "columns": {
            "object_id": "Identifier of the Modal object that incurred the cost, such as an App.",
            "description": "Description of the Modal object that incurred the cost.",
            "environment_name": "Name of the Modal environment that contains the object.",
            "interval_start": "Start of the billing interval in UTC.",
            "cost": "Cost for the billing interval before credits, reservations, and the network egress allowance.",
            "tags": "User-defined tags associated with the object during the billing interval.",
        },
    }
    for name, resolution in (("billing_report_daily", "Daily"), ("billing_report_hourly", "Hourly"))
}

CANONICAL_DESCRIPTIONS["billing_summary"] = {
    "description": "Workspace cost for each monthly billing cycle, before and after adjustments.",
    "docs_url": "https://modal.com/docs/sdk/py/latest/Workspace#billingsummary",
    "columns": {
        "cycle_start": "Start of the billing cycle in UTC.",
        "cycle_end": "End of the billing cycle in UTC.",
        "metered_cost": "Cost for the billing cycle before adjustments.",
        "billed_cost": "Cost actually invoiced for the billing cycle, including all adjustments.",
        "metered_cost_breakdown": "Metered cost by the Modal resource that generated it.",
        "adjustments": "Adjustments, such as plan credits, that make up the difference between metered and billed cost.",
    },
}
CANONICAL_DESCRIPTIONS["apps"] = {
    "description": "Modal Apps that are running, deployed, or recently stopped, in each environment of the workspace.",
    "docs_url": "https://modal.com/docs/cli/latest/app#modal-app-list",
    "columns": {
        "app_id": "Identifier of the App. Billing reports use it as the object ID.",
        "name": "Name of the App.",
        "description": "Description of the App.",
        "state": "Lifecycle state of the App, such as deployed, ephemeral, or stopped.",
        "environment_name": "Name of the Modal environment that contains the App.",
        "created_at": "Time when the App was created.",
        "stopped_at": "Time when the App was stopped.",
        "n_running_tasks": "Number of containers that run for the App at sync time.",
    },
}
CANONICAL_DESCRIPTIONS["sandboxes"] = {
    "description": "Modal Sandboxes of each App, including finished Sandboxes.",
    "docs_url": "https://modal.com/docs/sdk/py/latest/Sandbox#list",
    "columns": {
        "id": "Identifier of the Sandbox.",
        "name": "Name of the Sandbox.",
        "app_id": "Identifier of the App that contains the Sandbox.",
        "environment_name": "Name of the Modal environment that contains the Sandbox.",
        "created_at": "Time when the Sandbox was created.",
        "finished_at": "Time when the Sandbox finished.",
        "status": "Final status of the Sandbox, such as success, failure, or timeout. Empty while it runs.",
        "exit_code": "Exit code of the Sandbox entrypoint after it finished.",
        "tags": "User-defined tags of the Sandbox.",
    },
}
CANONICAL_DESCRIPTIONS["app_deployments"] = {
    "description": "Deployment history of each deployed Modal App, one row per deployed version.",
    "docs_url": "https://modal.com/docs/cli/latest/app#modal-app-history",
    "columns": {
        "app_id": "Identifier of the App.",
        "app_name": "Name of the App.",
        "environment_name": "Name of the Modal environment that contains the App.",
        "version": "Version number of the deployment.",
        "is_production": "Whether this version serves the App at sync time.",
        "deployed_at": "Time when the version was deployed.",
        "deployed_by": "Workspace member who deployed the version.",
        "client_version": "Version of the Modal client that deployed the version.",
        "tag": "Tag given to the deployment.",
        "deployment_type": "How the version was created, such as standard or rollback.",
        "rollback_version": "Version that a rollback deployment restored.",
        "commit_hash": "Git commit of the deployed code.",
        "commit_dirty": "Whether the working tree had uncommitted changes at deploy time.",
        "committed_at": "Time of the Git commit of the deployed code.",
    },
}
CANONICAL_DESCRIPTIONS["workspace_members"] = {
    "description": "Members of the Modal workspace and their roles.",
    "docs_url": "https://modal.com/docs/sdk/py/latest/Workspace#memberslist",
    "columns": {
        "user_id": "Identifier of the Modal user.",
        "name": "Display name of the member.",
        "email": "Email address of the member.",
        "role": "Role of the member in the workspace, such as user, manager, or owner.",
        "identity_provider": "Identity provider the member signs in with, such as GitHub or SAML.",
        "joined_at": "Time when the member joined the workspace.",
        "last_active_at": "Time when the member was last active.",
        "deleted_at": "Time when the member was removed from the workspace.",
    },
}
