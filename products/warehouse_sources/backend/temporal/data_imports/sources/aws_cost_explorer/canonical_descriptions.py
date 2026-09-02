from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_COST_AND_USAGE_DOCS_URL = (
    "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetCostAndUsage.html"
)

_COST_AND_USAGE_COLUMNS: dict[str, str] = {
    "period_start": "Inclusive start of the billing period the row covers.",
    "period_end": "Exclusive end of the billing period the row covers.",
    "granularity": "Bucket size AWS aggregated the period to (DAILY or MONTHLY).",
    "estimated": "Whether the amounts are still estimated. AWS restates recent periods until the bill finalizes.",
    "service": "AWS service the cost is attributed to, from the SERVICE dimension (for example 'Amazon Elastic Compute Cloud - Compute').",
    "linked_account": "Account ID of the member account the cost belongs to, from the LINKED_ACCOUNT dimension.",
    "amortized_cost_amount": "Effective cost with upfront reservation and Savings Plans fees spread across the periods they cover.",
    "amortized_cost_unit": "Currency of the amortized cost.",
    "blended_cost_amount": "Cost calculated with the blended rate, the average rate across the accounts in the organization.",
    "blended_cost_unit": "Currency of the blended cost.",
    "net_amortized_cost_amount": "Amortized cost after all discounts have been applied.",
    "net_amortized_cost_unit": "Currency of the net amortized cost.",
    "net_unblended_cost_amount": "Unblended cost after all discounts have been applied.",
    "net_unblended_cost_unit": "Currency of the net unblended cost.",
    "unblended_cost_amount": "Charges as they appear on the bill before amortization, using the account's own rates.",
    "unblended_cost_unit": "Currency of the unblended cost.",
    "usage_quantity_amount": "Amount of usage recorded for the period. Only meaningful when the rows share one usage type, since AWS sums across usage types with different units.",
    "usage_quantity_unit": "Unit the usage quantity is measured in.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "cost_and_usage_daily": {
        "description": "Daily AWS cost and usage from Cost Explorer, grouped by service and linked account.",
        "docs_url": _COST_AND_USAGE_DOCS_URL,
        "columns": _COST_AND_USAGE_COLUMNS,
    },
    "cost_and_usage_monthly": {
        "description": "Monthly AWS cost and usage from Cost Explorer, grouped by service and linked account.",
        "docs_url": _COST_AND_USAGE_DOCS_URL,
        "columns": _COST_AND_USAGE_COLUMNS,
    },
    "reservation_utilization_daily": {
        "description": "Daily Reserved Instance utilization and savings totals across the account.",
        "docs_url": "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetReservationUtilization.html",
        "columns": {
            "period_start": "Inclusive start of the period the utilization covers.",
            "period_end": "Exclusive end of the period the utilization covers.",
            "granularity": "Bucket size AWS aggregated the period to (DAILY).",
            "utilization_percentage": "Percentage of the purchased reservation hours that were used.",
            "utilization_percentage_in_units": "Percentage of the purchased reservation normalized units that were used.",
            "purchased_hours": "Reservation hours purchased for the period.",
            "purchased_units": "Reservation normalized units purchased for the period.",
            "total_actual_hours": "Reservation hours actually used in the period.",
            "total_actual_units": "Reservation normalized units actually used in the period.",
            "unused_hours": "Purchased reservation hours that went unused.",
            "unused_units": "Purchased reservation normalized units that went unused.",
            "on_demand_cost_of_ri_hours_used": "What the used reservation hours would have cost at On-Demand rates.",
            "net_ri_savings": "Savings from the reservations after subtracting their upfront and recurring fees.",
            "total_potential_ri_savings": "Savings that would have been made had every purchased reservation hour been used.",
            "amortized_upfront_fee": "Upfront reservation fee spread over the period.",
            "amortized_recurring_fee": "Recurring monthly reservation fee spread over the period.",
            "total_amortized_fee": "Total amortized reservation fee for the period.",
            "ri_cost_for_unused_hours": "Cost of the reservation hours that went unused.",
            "realized_savings": "Savings realized from used reservation hours, net of the amortized fees.",
            "unrealized_savings": "Savings that were missed because reservation hours went unused.",
        },
    },
    "savings_plans_utilization_daily": {
        "description": "Daily Savings Plans commitment utilization and net savings across the account.",
        "docs_url": "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetSavingsPlansUtilization.html",
        "columns": {
            "period_start": "Inclusive start of the period the utilization covers.",
            "period_end": "Exclusive end of the period the utilization covers.",
            "granularity": "Bucket size AWS aggregated the period to (DAILY).",
            "total_commitment": "Total Savings Plans commitment for the period.",
            "used_commitment": "Amount of the commitment that was used.",
            "unused_commitment": "Amount of the commitment that went unused.",
            "utilization_percentage": "Share of the commitment that was used, as a percentage.",
            "savings_net_savings": "Savings from the Savings Plans compared to paying On-Demand rates.",
            "savings_on_demand_cost_equivalent": "What the Savings Plans usage would have cost at On-Demand rates.",
            "amortized_commitment_amortized_recurring_commitment": "Recurring Savings Plans fee spread over the period.",
            "amortized_commitment_amortized_upfront_commitment": "Upfront Savings Plans fee spread over the period.",
            "amortized_commitment_total_amortized_commitment": "Total amortized Savings Plans commitment for the period.",
        },
    },
}
