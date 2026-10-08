from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_EVENT_COLUMNS = {
    "event_id": "The identifier that CloudTrail assigns to the event.",
    "event_name": "The AWS API action recorded by the event.",
    "event_source": "The AWS service that received the request.",
    "event_time": "The time of the event in UTC.",
    "username": "The user name associated with the event.",
    "access_key_id": "The access key ID used for the request.",
    "read_only": "Indicates whether the recorded operation only reads resources.",
    "resources": "The names and types of resources referenced by the event.",
    "cloud_trail_event": "The full CloudTrail event as a JSON string.",
    "region": "The AWS region selected for this import.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "events": {
        "description": "Management events returned by CloudTrail event history within the past 90 days.",
        "docs_url": "https://docs.aws.amazon.com/awscloudtrail/latest/APIReference/API_LookupEvents.html",
        "columns": _EVENT_COLUMNS,
    },
    "insight_events": {
        "description": "Insights events from trails with Insights enabled, within the past 90 days.",
        "docs_url": "https://docs.aws.amazon.com/awscloudtrail/latest/APIReference/API_LookupEvents.html",
        "columns": _EVENT_COLUMNS,
    },
    "trails": {
        "description": "Trail settings for the selected region, including shadow trails from other regions or organization accounts.",
        "docs_url": "https://docs.aws.amazon.com/awscloudtrail/latest/APIReference/API_DescribeTrails.html",
        "columns": {
            "trail_arn": "The ARN that identifies the trail.",
            "name": "The trail name.",
            "home_region": "The AWS region where the trail was created.",
            "s3_bucket_name": "The S3 bucket that receives the trail logs.",
            "s3_key_prefix": "The prefix used for log objects in the S3 bucket.",
            "is_multi_region_trail": "Indicates whether the trail records events across AWS regions.",
            "is_organization_trail": "Indicates whether the trail applies to an AWS organization.",
            "log_file_validation_enabled": "Indicates whether CloudTrail creates digest files for log validation.",
            "include_global_service_events": "Indicates whether the trail records global service events.",
            "has_insight_selectors": "Indicates whether the trail has Insights selectors.",
            "region": "The AWS region selected for this import.",
        },
    },
    "event_data_stores": {
        "description": "CloudTrail Lake event store settings in the selected region. These rows do not contain stored events.",
        "docs_url": "https://docs.aws.amazon.com/awscloudtrail/latest/APIReference/API_ListEventDataStores.html",
        "columns": {
            "event_data_store_arn": "The ARN that identifies the event store.",
            "name": "The event store name.",
            "status": "The event store status.",
            "created_timestamp": "The time when the event store was created.",
            "updated_timestamp": "The time when the event store was last changed.",
            "retention_period": "The number of days for which the event store retains events.",
            "advanced_event_selectors": "The rules that select events for this store.",
            "multi_region_enabled": "Indicates whether the store includes events from multiple AWS regions.",
            "organization_enabled": "Indicates whether the store includes events from an AWS organization.",
            "termination_protection_enabled": "Indicates whether deletion protection is enabled.",
            "region": "The AWS region selected for this import.",
        },
    },
}
