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

for name, endpoint in ENDPOINTS.items():
    if endpoint.fanout is None and name != "recommendation_summaries":
        CANONICAL_DESCRIPTIONS[name]["columns"].update(
            {
                "finding": "Classification of the resource's optimization status.",
                "last_refresh_timestamp": "Time when Compute Optimizer last refreshed the recommendation, in UTC.",
                (
                    "lookback_period_in_days"
                    if name
                    in {
                        "lambda_function_recommendations",
                        "ecs_service_recommendations",
                        "rds_database_recommendations",
                    }
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
CANONICAL_DESCRIPTIONS["rds_database_recommendations"]["columns"].update(
    {
        "resource_arn": "Amazon Resource Name of the Aurora or RDS database.",
        "engine": "Database engine of the instance.",
        "current_db_instance_class": "DB instance class used by the database.",
        "instance_finding": "Classification of the DB instance's optimization status.",
        "storage_finding": "Classification of the DB storage's optimization status.",
        "instance_recommendation_options": "Recommended DB instance classes with projected utilization and potential savings.",
        "storage_recommendation_options": "Recommended storage configurations with potential savings.",
    }
)
CANONICAL_DESCRIPTIONS["idle_recommendations"]["columns"].update(
    {
        "resource_arn": "Amazon Resource Name of the idle resource.",
        "resource_id": "Unique identifier of the idle resource.",
        "resource_type": "Type of the idle resource, such as an EC2 instance or EBS volume.",
        "finding_description": "Explanation of why Compute Optimizer considers the resource idle.",
    }
)
for name, endpoint in ENDPOINTS.items():
    if endpoint.fanout is not None:
        CANONICAL_DESCRIPTIONS[name]["columns"].update(
            {
                "metric_name": "Utilization metric that Compute Optimizer projects, such as Cpu or Memory.",
                "timestamp": "Start of the one-day period of the projected data point, in UTC.",
            }
        )
CANONICAL_DESCRIPTIONS["ec2_recommendation_projected_metrics"]["columns"].update(
    {
        "instance_arn": "Amazon Resource Name of the EC2 instance.",
        "recommended_instance_type": "Recommended EC2 instance type the projection applies to.",
        "rank": "Rank of the recommendation option. Rank 1 is the best option.",
        "value": "Projected maximum utilization for the period if the instance used the recommended type.",
    }
)
CANONICAL_DESCRIPTIONS["ecs_service_recommendation_projected_metrics"]["columns"].update(
    {
        "service_arn": "Amazon Resource Name of the ECS service.",
        "recommended_cpu_units": "Recommended CPU units the projection applies to.",
        "recommended_memory_size": "Recommended memory size, in MiB, the projection applies to.",
        "upper_bound_value": "Upper bound of the projected maximum utilization for the period.",
        "lower_bound_value": "Lower bound of the projected maximum utilization for the period.",
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
