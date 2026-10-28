from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "account_parents": {
        "description": "The root or organizational unit that each account sits directly under. Join to accounts on account_id and to organizational_units or roots on parent_id.",
        "docs_url": "https://docs.aws.amazon.com/organizations/latest/APIReference/API_ListParents.html",
        "columns": {
            "account_id": "The unique identifier (ID) of the account, a 12-digit number.",
            "parent_id": "The unique identifier (ID) of the parent entity: a root ID starting with 'r-' or an organizational unit ID starting with 'ou-'.",
            "parent_type": "The type of the parent entity: ROOT or ORGANIZATIONAL_UNIT.",
        },
    },
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
    "delegated_administrators": {
        "description": "Accounts in the organization that are designated as delegated administrators for an AWS service.",
        "docs_url": "https://docs.aws.amazon.com/organizations/latest/APIReference/API_DelegatedAdministrator.html",
        "columns": {
            "id": "The unique identifier (ID) of the delegated administrator's account.",
            "arn": "The Amazon Resource Name (ARN) of the delegated administrator's account.",
            "email": "The email address that is associated with the delegated administrator's AWS account.",
            "name": "The friendly name of the delegated administrator's account.",
            "status": "The status of the delegated administrator's account in the organization.",
            "state": "The lifecycle state of the delegated administrator's account in the organization.",
            "joined_method": "The method by which the delegated administrator's account joined the organization.",
            "joined_timestamp": "The date when the delegated administrator's account became a part of the organization.",
            "delegation_enabled_date": "The date when the account was made a delegated administrator.",
        },
    },
    "delegated_services": {
        "description": "The AWS services for which each delegated administrator account is a delegated administrator. One row per account and service.",
        "docs_url": "https://docs.aws.amazon.com/organizations/latest/APIReference/API_DelegatedService.html",
        "columns": {
            "account_id": "The unique identifier (ID) of the delegated administrator's account.",
            "service_principal": "The name of the AWS service, typically in the form servicename.amazonaws.com.",
            "delegation_enabled_date": "The date that the account became a delegated administrator for this service.",
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
    "policy_targets": {
        "description": "The roots, organizational units, and accounts that each policy is attached to. One row per attachment.",
        "docs_url": "https://docs.aws.amazon.com/organizations/latest/APIReference/API_PolicyTargetSummary.html",
        "columns": {
            "policy_id": "The unique identifier (ID) of the attached policy.",
            "policy_type": "The type of the attached policy, for example SERVICE_CONTROL_POLICY or TAG_POLICY.",
            "target_id": "The unique identifier (ID) of the policy target: a root, organizational unit, or account ID.",
            "arn": "The Amazon Resource Name (ARN) of the policy target.",
            "name": "The friendly name of the policy target.",
            "type": "The type of the policy target: ROOT, ORGANIZATIONAL_UNIT, or ACCOUNT.",
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
