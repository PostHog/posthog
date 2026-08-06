from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "account": {
        "description": "Account-level SES sending status, quota, and enforcement for the connected region.",
        "docs_url": "https://docs.aws.amazon.com/ses/latest/APIReference-V2/API_GetAccount.html",
        "columns": {
            "dedicated_ip_auto_warmup_enabled": "Whether automatic warm-up is enabled for the account's dedicated IP addresses.",
            "enforcement_status": "AWS's enforcement standing for the account (for example HEALTHY, PROBATION, or SHUTDOWN).",
            "production_access_enabled": "Whether the account is out of the SES sandbox and has production sending access.",
            "sending_enabled": "Whether sending is currently enabled for the account.",
            "send_quota_max24_hour_send": "Maximum number of emails the account can send in a 24-hour period.",
            "send_quota_max_send_rate": "Maximum number of emails the account can send per second.",
            "send_quota_sent_last24_hours": "Number of emails sent from the account in the last 24 hours.",
            "suppression_attributes_suppressed_reasons": "Reasons (BOUNCE, COMPLAINT) that add an address to the account suppression list automatically.",
        },
    },
    "configuration_sets": {
        "description": "Configuration sets defined in the account, used to group rules applied to sent email.",
        "docs_url": "https://docs.aws.amazon.com/ses/latest/APIReference-V2/API_ListConfigurationSets.html",
        "columns": {
            "configuration_set_name": "Name of the configuration set.",
        },
    },
    "email_identities": {
        "description": "Email addresses and domains registered with the account, with their verification and sending status.",
        "docs_url": "https://docs.aws.amazon.com/ses/latest/APIReference-V2/API_ListEmailIdentities.html",
        "columns": {
            "identity_name": "The email address or domain of the identity.",
            "identity_type": "Whether the identity is an EMAIL_ADDRESS, DOMAIN, or MANAGED_DOMAIN.",
            "sending_enabled": "Whether the identity is allowed to send email.",
            "verification_status": "Verification state of the identity (for example SUCCESS, PENDING, or FAILED).",
        },
    },
    "suppressed_destinations": {
        "description": "Addresses on the account suppression list, with the reason each was suppressed.",
        "docs_url": "https://docs.aws.amazon.com/ses/latest/APIReference-V2/API_ListSuppressedDestinations.html",
        "columns": {
            "email_address": "The suppressed email address.",
            "reason": "Why the address was suppressed: BOUNCE or COMPLAINT.",
            "last_update_time": "When the address was last added to or updated on the suppression list.",
        },
    },
}
