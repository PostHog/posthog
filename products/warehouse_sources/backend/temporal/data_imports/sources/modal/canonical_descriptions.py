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
