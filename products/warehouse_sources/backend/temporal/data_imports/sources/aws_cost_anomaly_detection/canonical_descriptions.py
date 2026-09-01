from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "anomalies": {
        "description": "Unusual cost patterns AWS detected on the account, with the spend impact and the root causes of each one. AWS keeps anomalies for 90 days.",
        "docs_url": "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetAnomalies.html",
        "columns": {
            "anomaly_id": "Unique identifier for the anomaly.",
            "anomaly_start_date": "First day the anomaly was detected.",
            "anomaly_end_date": "Last day the anomaly was detected. AWS keeps moving this forward while the anomaly is ongoing.",
            "dimension_value": "Dimension the anomaly was detected on, for example the AWS service in a service monitor.",
            "monitor_arn": "ARN of the cost monitor that generated the anomaly.",
            "feedback": "Feedback submitted for the anomaly in the console: YES, NO or PLANNED_ACTIVITY.",
            "anomaly_score_current_score": "Last observed anomaly score. A higher score means more anomalous.",
            "anomaly_score_max_score": "Highest score observed over the anomaly's date interval.",
            "impact_max_impact": "Largest single-day dollar impact observed for the anomaly.",
            "impact_total_impact": "Cumulative dollar difference between actual and expected spend, calculated as total actual spend minus total expected spend.",
            "impact_total_actual_spend": "Cumulative dollars actually spent during the anomaly.",
            "impact_total_expected_spend": "Cumulative dollars AWS expected to be spent, predicted from the account's historical spending pattern.",
            "impact_total_impact_percentage": "Total impact as a percentage of total expected spend.",
            "root_causes": "JSON array of the root causes AWS identified, each with the service, region, linked account, usage type, and the dollars it contributed to the total impact.",
        },
    },
    "anomaly_monitors": {
        "description": "Cost monitors that continuously inspect the account's spend for anomalies.",
        "docs_url": "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetAnomalyMonitors.html",
        "columns": {
            "monitor_arn": "ARN of the monitor.",
            "monitor_name": "Name of the monitor.",
            "monitor_type": "DIMENSIONAL for an AWS managed monitor that tracks values within one dimension, CUSTOM for a customer managed monitor over specific dimension values.",
            "monitor_dimension": "Dimension an AWS managed monitor analyzes: SERVICE, LINKED_ACCOUNT, TAG or COST_CATEGORY. Empty for customer managed monitors.",
            "monitor_specification": "JSON expression controlling which costs the monitor analyzes.",
            "dimensional_value_count": "Number of dimension values the monitor evaluates.",
            "creation_date": "Date the monitor was created.",
            "last_updated_date": "Date the monitor was last updated.",
            "last_evaluated_date": "Date the monitor last evaluated the account for anomalies.",
        },
    },
    "anomaly_subscriptions": {
        "description": "Alert subscriptions that notify subscribers about anomalies detected by their associated cost monitors.",
        "docs_url": "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetAnomalySubscriptions.html",
        "columns": {
            "subscription_arn": "ARN of the alert subscription.",
            "subscription_name": "Name of the alert subscription.",
            "account_id": "Account the subscription belongs to.",
            "monitor_arn_list": "JSON array of the cost monitor ARNs the subscription watches.",
            "subscribers": "JSON array of subscribers to notify, each with an email address or SNS topic ARN, its type, and whether the subscriber confirmed the notifications.",
            "frequency": "How often notifications are sent: DAILY, WEEKLY or IMMEDIATE.",
            "threshold": "Deprecated absolute dollar impact an anomaly must exceed to trigger a notification. AWS treats it as shorthand for a threshold expression.",
            "threshold_expression": "JSON expression selecting which anomalies trigger alerts, by absolute or percentage total impact.",
        },
    },
}
