from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "savings_plans": {
        "description": "Purchased Savings Plans with their commitment, payment option, term, and state.",
        "docs_url": "https://docs.aws.amazon.com/savingsplans/latest/APIReference/API_SavingsPlan.html",
        "columns": {
            "savings_plan_arn": "Amazon Resource Name that identifies the Savings Plan.",
            "savings_plan_id": "Identifier of the Savings Plan.",
            "commitment": "Hourly commitment for the Savings Plan.",
            "currency": "Currency for the Savings Plan.",
            "start": "Start time of the Savings Plan.",
            "end": "End time of the Savings Plan.",
            "state": "Current state of the Savings Plan.",
            "payment_option": "Payment option for the Savings Plan.",
            "term_duration_in_seconds": "Plan duration in seconds.",
            "tags": "Tags attached to the Savings Plan.",
        },
    },
    "utilization_daily": {
        "description": "Daily use of Savings Plans commitments and the resulting savings.",
        "docs_url": "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetSavingsPlansUtilization.html",
        "columns": {
            "period_start": "Inclusive start of the reporting period in UTC.",
            "period_end": "Exclusive end of the reporting period in UTC.",
            "utilization_total_commitment": "Total commitment during the period.",
            "utilization_used_commitment": "Commitment used during the period.",
            "utilization_unused_commitment": "Commitment that was not used during the period.",
            "utilization_utilization_percentage": "Percentage of the commitment used during the period.",
            "savings_net_savings": "Net savings compared with on-demand pricing.",
            "savings_on_demand_cost_equivalent": "Equivalent cost at on-demand prices.",
        },
    },
    "utilization_details_daily": {
        "description": "Daily use, savings, and attributes for each Savings Plan.",
        "docs_url": "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetSavingsPlansUtilizationDetails.html",
        "columns": {
            "savings_plan_arn": "Amazon Resource Name that identifies the Savings Plan.",
            "period_start": "Inclusive start of the reporting period in UTC.",
            "period_end": "Exclusive end of the reporting period in UTC.",
            "attributes": "Attributes associated with the Savings Plan.",
            "utilization_total_commitment": "Total commitment during the period.",
            "utilization_used_commitment": "Commitment used during the period.",
            "utilization_unused_commitment": "Commitment that was not used during the period.",
            "savings_net_savings": "Net savings compared with on-demand pricing.",
        },
    },
    "coverage_daily": {
        "description": "Daily spend covered by Savings Plans and the remaining on-demand cost.",
        "docs_url": "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetSavingsPlansCoverage.html",
        "columns": {
            "period_start": "Inclusive start of the reporting period in UTC.",
            "period_end": "Exclusive end of the reporting period in UTC.",
            "coverage_coverage_percentage": "Percentage of eligible spend covered by Savings Plans.",
            "coverage_spend_covered_by_savings_plans": "Spend covered by Savings Plans.",
            "coverage_on_demand_cost": "Eligible spend that Savings Plans did not cover.",
            "coverage_total_cost": "Total eligible spend during the period.",
        },
    },
}
