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
