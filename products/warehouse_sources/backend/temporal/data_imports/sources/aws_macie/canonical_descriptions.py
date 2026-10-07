from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "findings": {
        "description": "Reports of sensitive data or potential security issues in S3 buckets and objects.",
        "docs_url": "https://docs.aws.amazon.com/macie/latest/APIReference/findings-describe.html",
        "columns": {
            "id": "The finding identifier.",
            "account_id": "The AWS account associated with the finding.",
            "region": "The AWS region where Macie created the finding.",
            "category": "The finding category: CLASSIFICATION for sensitive data or POLICY for bucket security.",
            "created_at": "The UTC time when Macie created the finding.",
            "updated_at": "The UTC time when Macie last changed the finding.",
            "severity": "The severity description and numeric score.",
            "resources_affected": "The S3 bucket and object affected by the finding.",
            "classification_details": "The discovery job and classification results for a sensitive data finding.",
            "policy_details": "The action and actor details for a policy finding.",
            "sample": "Whether Macie generated this finding with example data.",
        },
    },
    "buckets": {
        "description": "Inventory and security metadata for S3 buckets that Macie monitors.",
        "docs_url": "https://docs.aws.amazon.com/macie/latest/APIReference/datasources-s3.html",
        "columns": {
            "bucket_arn": "The Amazon Resource Name of the bucket.",
            "bucket_name": "The bucket name.",
            "account_id": "The AWS account that owns the bucket.",
            "region": "The AWS region where the bucket is located.",
            "bucket_created_at": "The UTC time when the bucket was created.",
            "last_updated": "The UTC time when Macie last retrieved metadata for the bucket.",
            "object_count": "The number of objects in the bucket.",
            "size_in_bytes": "The total storage size of the bucket in bytes.",
            "public_access": "The public access settings and effective permissions for the bucket.",
            "sensitivity_score": "The sensitivity score that Macie assigned to the bucket.",
        },
    },
    "classification_jobs": {
        "description": "Summaries of sensitive data discovery jobs and their status.",
        "docs_url": "https://docs.aws.amazon.com/macie/latest/APIReference/jobs-list.html",
        "columns": {
            "job_id": "The job identifier.",
            "region": "The AWS region selected for this sync.",
            "name": "The custom job name.",
            "created_at": "The UTC time when the job was created.",
            "job_status": "The job status.",
            "job_type": "Whether the job runs once or on a schedule.",
            "bucket_criteria": "Conditions that select the S3 buckets for analysis.",
            "bucket_definitions": "The accounts and specific S3 buckets selected for analysis.",
            "last_run_error_status": "Whether account or bucket access errors occurred during the last run.",
        },
    },
    "members": {
        "description": "AWS accounts associated with the Macie administrator, including former members.",
        "docs_url": "https://docs.aws.amazon.com/macie/latest/APIReference/members.html",
        "columns": {
            "account_id": "The member account identifier.",
            "administrator_account_id": "The Macie administrator account identifier.",
            "arn": "The Amazon Resource Name assigned to the account by Macie.",
            "email": "The email address for the account.",
            "region": "The AWS region selected for this sync.",
            "relationship_status": "The account relationship with the Macie administrator.",
            "invited_at": "The UTC time when Macie sent the membership invitation.",
            "updated_at": "The UTC time when the account status or settings last changed.",
        },
    },
}
