from products.warehouse_sources.backend.temporal.data_imports.sources.aws_compute_optimizer.settings import (
    API_DOCS_URL,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    name: {
        "description": endpoint.description,
        "docs_url": f"{API_DOCS_URL}API_{endpoint.operation}.html",
        "columns": {
            "account_id": "AWS account that owns the resources.",
            "region": "AWS region from which this source reads recommendations.",
        },
    }
    for name, endpoint in ENDPOINTS.items()
}

for name in ENDPOINTS:
    if name != "recommendation_summaries":
        CANONICAL_DESCRIPTIONS[name]["columns"].update(
            {
                "finding": "Classification of the resource's optimization status.",
                "last_refresh_timestamp": "Time when Compute Optimizer last refreshed the recommendation, in UTC.",
                (
                    "lookback_period_in_days"
                    if name in {"lambda_function_recommendations", "ecs_service_recommendations"}
                    else "look_back_period_in_days"
                ): "Number of days of utilization data used to generate the recommendation.",
                "utilization_metrics": "Utilization measurements used to evaluate the resource.",
            }
        )

CANONICAL_DESCRIPTIONS["ec2_instance_recommendations"]["columns"].update(
    {
        "instance_arn": "Amazon Resource Name of the EC2 instance.",
        "current_instance_type": "EC2 instance type used by the resource.",
        "recommendation_options": "Recommended instance types, performance risks, utilization projections, and potential savings.",
    }
)
CANONICAL_DESCRIPTIONS["auto_scaling_group_recommendations"]["columns"].update(
    {
        "auto_scaling_group_arn": "Amazon Resource Name of the Auto Scaling group.",
        "recommendation_options": "Recommended configurations for the Auto Scaling group.",
    }
)
CANONICAL_DESCRIPTIONS["lambda_function_recommendations"]["columns"].update(
    {
        "function_arn": "Amazon Resource Name of the Lambda function.",
        "function_version": "Version of the Lambda function evaluated by Compute Optimizer.",
        "memory_size_recommendation_options": "Recommended memory sizes with projected utilization and potential savings.",
    }
)
CANONICAL_DESCRIPTIONS["ecs_service_recommendations"]["columns"].update(
    {
        "service_arn": "Amazon Resource Name of the ECS service.",
        "service_recommendation_options": "Recommended CPU and memory configurations with potential savings.",
    }
)
CANONICAL_DESCRIPTIONS["ebs_volume_recommendations"]["columns"].update(
    {
        "volume_arn": "Amazon Resource Name of the EBS volume.",
        "volume_recommendation_options": "Recommended volume configurations with performance risks and potential savings.",
    }
)
CANONICAL_DESCRIPTIONS["recommendation_summaries"]["columns"].update(
    {
        "recommendation_resource_type": "Type of AWS resource covered by the summary.",
        "summaries": "Counts of resources grouped by optimization finding.",
        "savings_opportunity_estimated_monthly_savings_value": "Estimated monthly savings for this resource type.",
        "savings_opportunity_estimated_monthly_savings_currency": "Currency used for the estimated monthly savings.",
    }
)
