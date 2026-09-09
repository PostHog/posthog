from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "accounts": {
        "description": "Every AWS account in the organization. The dimension table that maps a 12-digit account ID to a human-readable account name.",
        "docs_url": "https://docs.aws.amazon.com/organizations/latest/APIReference/API_Account.html",
        "columns": {
            "id": "The unique identifier (ID) of the account, a 12-digit number.",
            "arn": "The Amazon Resource Name (ARN) of the account.",
            "email": "The email address associated with the AWS account, used as the root user sign-in name.",
            "name": "The friendly name of the account.",
            "state": "The state of the account in the organization: ACTIVE, SUSPENDED, or PENDING_CLOSURE.",
            "joined_method": "How the account joined the organization: INVITED for an invited account, CREATED for one created by the organization.",
            "joined_timestamp": "The date the account became part of the organization.",
            "paths": "The paths of the account in the organization hierarchy, from the root down to the account.",
        },
    },
    "organization": {
        "description": "The organization itself, including its management account and which functionality is enabled. One row.",
        "docs_url": "https://docs.aws.amazon.com/organizations/latest/APIReference/API_Organization.html",
        "columns": {
            "id": "The unique identifier (ID) of the organization, starting with 'o-'.",
            "arn": "The Amazon Resource Name (ARN) of the organization.",
            "feature_set": "The functionality available to the organization: ALL for all features, or CONSOLIDATED_BILLING for consolidated billing only.",
            "master_account_arn": "The Amazon Resource Name (ARN) of the management account of the organization.",
            "master_account_email": "The email address of the management account of the organization.",
            "master_account_id": "The unique identifier (ID) of the management account of the organization.",
        },
    },
    "organizational_units": {
        "description": "Organizational units (OUs) in the account hierarchy, each with the root or OU it sits under.",
        "docs_url": "https://docs.aws.amazon.com/organizations/latest/APIReference/API_OrganizationalUnit.html",
        "columns": {
            "id": "The unique identifier (ID) of the organizational unit, starting with 'ou-'.",
            "arn": "The Amazon Resource Name (ARN) of the organizational unit.",
            "name": "The friendly name of the organizational unit.",
            "path": "The path of the organizational unit in the organization hierarchy.",
            "parent_id": "The ID of the root or organizational unit this unit is a child of.",
            "parent_type": "Whether the parent is a ROOT or an ORGANIZATIONAL_UNIT.",
        },
    },
    "policies": {
        "description": "Policies in the organization, across every policy type it supports. Policy contents are not included.",
        "docs_url": "https://docs.aws.amazon.com/organizations/latest/APIReference/API_PolicySummary.html",
        "columns": {
            "id": "The unique identifier (ID) of the policy, starting with 'p-'.",
            "arn": "The Amazon Resource Name (ARN) of the policy.",
            "name": "The friendly name of the policy.",
            "description": "The description of the policy.",
            "type": "The type of policy, for example SERVICE_CONTROL_POLICY or TAG_POLICY.",
            "aws_managed": "True when the policy is managed by AWS, which means it can be attached to entities but not edited.",
        },
    },
    "resource_tags": {
        "description": "Tags attached to accounts, roots, organizational units, and policies. One row per tag.",
        "docs_url": "https://docs.aws.amazon.com/organizations/latest/APIReference/API_ListTagsForResource.html",
        "columns": {
            "resource_id": "The ID of the tagged resource: an account ID, root ID, organizational unit ID, or policy ID.",
            "resource_type": "The kind of resource the tag is attached to: ACCOUNT, ROOT, ORGANIZATIONAL_UNIT, or POLICY.",
            "key": "The key of the tag.",
            "value": "The value of the tag.",
        },
    },
    "roots": {
        "description": "Roots of the organization, with the policy types currently enabled on each.",
        "docs_url": "https://docs.aws.amazon.com/organizations/latest/APIReference/API_Root.html",
        "columns": {
            "id": "The unique identifier (ID) of the root, starting with 'r-'.",
            "arn": "The Amazon Resource Name (ARN) of the root.",
            "name": "The friendly name of the root.",
            "policy_types": "The policy types currently enabled for the root, each with its type and status.",
        },
    },
}
