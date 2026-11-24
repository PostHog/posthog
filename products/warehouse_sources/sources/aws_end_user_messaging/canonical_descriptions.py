from products.warehouse_sources.sources.sdk import CanonicalDescriptions

_DOCS = "https://docs.aws.amazon.com/pinpoint/latest/apireference_smsvoicev2/API_{}.html"
_MESSAGE_TYPE = "TRANSACTIONAL for critical or time-sensitive messages, PROMOTIONAL for other messages."
_SELF_MANAGED_OPT_OUTS = (
    "False when AWS replies to HELP and STOP messages and adds the sender to the opt-out list. "
    "True when you handle these messages yourself."
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "phone_numbers": {
        "description": "Origination phone numbers that the account leases in the configured region.",
        "docs_url": _DOCS.format("PhoneNumberInformation"),
        "columns": {
            "phone_number_arn": "The Amazon Resource Name (ARN) of the phone number.",
            "phone_number_id": "The unique identifier of the phone number.",
            "phone_number": "The phone number, in E.164 format.",
            "status": "The status of the phone number: PENDING, ACTIVE, ASSOCIATING, DISASSOCIATING, or DELETED.",
            "iso_country_code": "The country or region, as an ISO 3166-1 alpha-2 code.",
            "message_type": _MESSAGE_TYPE,
            "number_capabilities": "Whether the number can send text messages, voice calls, or both.",
            "number_type": "The number type: SHORT_CODE, LONG_CODE, TOLL_FREE, TEN_DLC, or SIMULATOR.",
            "monthly_leasing_price": "The monthly price, in US dollars, to lease the phone number.",
            "two_way_enabled": "True when the number can receive incoming text messages through the two-way channel.",
            "two_way_channel_arn": "The ARN of the two-way channel that receives incoming messages.",
            "two_way_channel_role": "The IAM role that the service assumes to post incoming messages.",
            "self_managed_opt_outs_enabled": _SELF_MANAGED_OPT_OUTS,
            "opt_out_list_name": "The name of the opt-out list of the phone number.",
            "international_sending_enabled": "True when the number can send messages to other countries.",
            "deletion_protection_enabled": "True when the phone number cannot be deleted.",
            "pool_id": "The identifier of the pool that holds the phone number.",
            "registration_id": "The identifier of the registration of the phone number.",
            "created_timestamp": "The time AWS created the phone number, in UTC.",
        },
    },
    "pools": {
        "description": "Pools that group origination identities for sending.",
        "docs_url": _DOCS.format("PoolInformation"),
        "columns": {
            "pool_arn": "The Amazon Resource Name (ARN) of the pool.",
            "pool_id": "The unique identifier of the pool.",
            "status": "The status of the pool: CREATING, ACTIVE, or DELETING.",
            "message_type": _MESSAGE_TYPE,
            "two_way_enabled": "True when the pool can receive incoming text messages through the two-way channel.",
            "two_way_channel_arn": "The ARN of the two-way channel that receives incoming messages.",
            "two_way_channel_role": "The IAM role that the service assumes to post incoming messages.",
            "self_managed_opt_outs_enabled": _SELF_MANAGED_OPT_OUTS,
            "opt_out_list_name": "The name of the opt-out list of the pool.",
            "shared_routes_enabled": "True when messages can go through numbers and sender IDs that AWS shares.",
            "deletion_protection_enabled": "True when the pool cannot be deleted.",
            "created_timestamp": "The time AWS created the pool, in UTC.",
        },
    },
    "sender_ids": {
        "description": "Alphanumeric sender IDs, one row for each sender ID and country.",
        "docs_url": _DOCS.format("SenderIdInformation"),
        "columns": {
            "sender_id_arn": "The Amazon Resource Name (ARN) of the sender ID.",
            "sender_id": "The alphanumeric sender ID.",
            "iso_country_code": "The country or region, as an ISO 3166-1 alpha-2 code.",
            "message_types": "The message types that the sender ID can send: TRANSACTIONAL, PROMOTIONAL, or both.",
            "monthly_leasing_price": "The monthly leasing price, in US dollars.",
            "deletion_protection_enabled": "True when the sender ID cannot be deleted.",
            "registered": "True when the sender ID is registered.",
            "registration_id": "The identifier of the registration of the sender ID.",
        },
    },
    "configuration_sets": {
        "description": "Configuration sets, which hold the event destinations and default settings for sending.",
        "docs_url": _DOCS.format("ConfigurationSetInformation"),
        "columns": {
            "configuration_set_arn": "The Amazon Resource Name (ARN) of the configuration set.",
            "configuration_set_name": "The name of the configuration set.",
            "event_destinations": "The event destinations that get the message events, with their event types.",
            "default_message_type": _MESSAGE_TYPE,
            "default_sender_id": "The default sender ID of the configuration set.",
            "default_message_feedback_enabled": "True when message feedback is enabled.",
            "created_timestamp": "The time AWS created the configuration set, in UTC.",
            "protect_configuration_id": "The identifier of the protect configuration of the configuration set.",
        },
    },
    "opt_out_lists": {
        "description": "Opt-out lists, which hold the destination numbers that do not get messages.",
        "docs_url": _DOCS.format("OptOutListInformation"),
        "columns": {
            "opt_out_list_arn": "The Amazon Resource Name (ARN) of the opt-out list.",
            "opt_out_list_name": "The name of the opt-out list.",
            "created_timestamp": "The time AWS created the opt-out list, in UTC.",
        },
    },
    "opted_out_numbers": {
        "description": "Destination phone numbers in each opt-out list.",
        "docs_url": _DOCS.format("OptedOutNumberInformation"),
        "columns": {
            "opt_out_list_arn": "The ARN of the opt-out list that holds the number.",
            "opt_out_list_name": "The name of the opt-out list that holds the number.",
            "opted_out_number": "The phone number that opted out, in E.164 format.",
            "opted_out_timestamp": "The time the number opted out, in UTC.",
            "end_user_opted_out": "True when the recipient opted out, false when the account added the number.",
        },
    },
    "keywords": {
        "description": "Keywords on phone numbers and pools, and the automatic action for each keyword.",
        "docs_url": _DOCS.format("KeywordInformation"),
        "columns": {
            "origination_identity_arn": "The ARN of the phone number or pool that has the keyword.",
            "origination_identity": "The identifier of the phone number or pool that has the keyword.",
            "keyword": "The keyword.",
            "keyword_message": "The message that AWS sends when a recipient sends the keyword.",
            "keyword_action": "The action for the keyword: AUTOMATIC_RESPONSE, OPT_OUT, or OPT_IN.",
        },
    },
    "registrations": {
        "description": "Registrations for phone numbers and sender IDs.",
        "docs_url": _DOCS.format("RegistrationInformation"),
        "columns": {
            "registration_arn": "The Amazon Resource Name (ARN) of the registration.",
            "registration_id": "The unique identifier of the registration.",
            "registration_type": "The type of registration form.",
            "registration_status": "The status of the registration, such as CREATED, SUBMITTED, REVIEWING, or COMPLETE.",
            "current_version_number": "The current version number of the registration.",
            "approved_version_number": "The version number of the registration that AWS approved.",
            "latest_denied_version_number": "The latest version number of the registration that AWS denied.",
            "additional_attributes": "Attributes that are specific to the registration type.",
            "created_timestamp": "The time AWS created the registration, in UTC.",
        },
    },
    "registration_associations": {
        "description": "Phone numbers and sender IDs that each registration covers.",
        "docs_url": _DOCS.format("RegistrationAssociationMetadata"),
        "columns": {
            "registration_arn": "The ARN of the registration.",
            "registration_id": "The identifier of the registration.",
            "registration_type": "The type of registration form.",
            "resource_arn": "The ARN of the phone number or sender ID that the registration covers.",
            "resource_id": "The identifier of the phone number or sender ID, such as a PhoneNumberId or SenderId.",
            "resource_type": "The type of the origination identity.",
            "iso_country_code": "The country or region, as an ISO 3166-1 alpha-2 code.",
            "phone_number": "The phone number that the registration covers, in E.164 format.",
        },
    },
    "registration_versions": {
        "description": "Versions of each registration, with their review history.",
        "docs_url": _DOCS.format("RegistrationVersionInformation"),
        "columns": {
            "registration_arn": "The ARN of the registration.",
            "registration_id": "The identifier of the registration.",
            "version_number": "The version number of the registration.",
            "registration_version_status": (
                "The status of the version, such as DRAFT, SUBMITTED, REVIEWING, APPROVED, DENIED, or ARCHIVED."
            ),
            "registration_version_status_history": (
                "The times the version entered each status, such as DraftTimestamp and ApprovedTimestamp, "
                "in UNIX epoch seconds."
            ),
            "denied_reasons": "The reasons AWS denied the version, with short and long descriptions.",
            "feedback": "Feedback from the review of the version, with comments and requirements.",
        },
    },
    "registration_field_values": {
        "description": (
            "Values of the form fields of each registration, one row for each field. "
            "When no version is requested, AWS returns the values of one version, which version_number gives."
        ),
        "docs_url": _DOCS.format("RegistrationFieldValueInformation"),
        "columns": {
            "registration_arn": "The ARN of the registration.",
            "registration_id": "The identifier of the registration.",
            "version_number": "The version number of the registration that the values belong to.",
            "field_path": "The path to the registration form field.",
            "text_value": "The text of a free form field.",
            "select_choices": "The values chosen for a select field.",
            "registration_attachment_id": "The identifier of the attachment for an attachment field.",
            "denied_reason": "The reason AWS denied the value of the field.",
            "feedback": "Feedback from the review of the field.",
        },
    },
    "pool_origination_identities": {
        "description": "Phone numbers and sender IDs in each pool.",
        "docs_url": _DOCS.format("OriginationIdentityMetadata"),
        "columns": {
            "pool_arn": "The ARN of the pool that holds the origination identity.",
            "pool_id": "The identifier of the pool that holds the origination identity.",
            "origination_identity_arn": "The ARN of the phone number or sender ID.",
            "origination_identity": "The identifier of the phone number or sender ID.",
            "iso_country_code": "The country or region, as an ISO 3166-1 alpha-2 code.",
            "number_capabilities": "Whether the origination identity can send text messages, voice calls, or both.",
            "phone_number": "The phone number, in E.164 format.",
        },
    },
    "verified_destination_numbers": {
        "description": "Destination phone numbers that are verified for a sandbox or simulator account.",
        "docs_url": _DOCS.format("VerifiedDestinationNumberInformation"),
        "columns": {
            "verified_destination_number_arn": "The Amazon Resource Name (ARN) of the verified destination number.",
            "verified_destination_number_id": "The unique identifier of the verified destination number.",
            "destination_phone_number": "The destination phone number, in E.164 format.",
            "status": "The status of the verification: PENDING or VERIFIED.",
            "created_timestamp": "The time AWS created the verified destination number, in UTC.",
        },
    },
    "protect_configurations": {
        "description": "Protect configurations, which control the countries that messages can go to.",
        "docs_url": _DOCS.format("ProtectConfigurationInformation"),
        "columns": {
            "protect_configuration_arn": "The Amazon Resource Name (ARN) of the protect configuration.",
            "protect_configuration_id": "The unique identifier of the protect configuration.",
            "created_timestamp": "The time AWS created the protect configuration, in UTC.",
            "account_default": "True when the protect configuration is the default of the account.",
            "deletion_protection_enabled": "True when the protect configuration cannot be deleted.",
        },
    },
    "spend_limits": {
        "description": "Monthly spend limits for text, voice, and media messages.",
        "docs_url": _DOCS.format("SpendLimit"),
        "columns": {
            "name": "The spend limit, such as TEXT_MESSAGE_MONTHLY_SPEND_LIMIT.",
            "enforced_limit": "The maximum, in US dollars, that the account can spend each month on this type.",
            "max_limit": "The highest monthly limit, in US dollars, that the account can set.",
            "overridden": "True when the enforced limit applies instead of the default limit.",
        },
    },
    "account_attributes": {
        "description": "Attributes of the account, such as the account tier.",
        "docs_url": _DOCS.format("AccountAttribute"),
        "columns": {
            "name": "The attribute: ACCOUNT_TIER or DEFAULT_PROTECT_CONFIGURATION_ID.",
            "value": "The value of the attribute.",
        },
    },
    "account_limits": {
        "description": "Quotas of the account for each resource type.",
        "docs_url": _DOCS.format("AccountLimit"),
        "columns": {
            "name": "The resource type of the quota, such as PHONE_NUMBERS or POOLS.",
            "used": "The quantity of the resource that the account uses now.",
            "max": "The quota that AWS sets for the resource type.",
        },
    },
}
