from products.warehouse_sources.sources.sdk import frozen

API_VERSION = "2022-03-31"
API_DOCS_URL = "https://docs.aws.amazon.com/pinpoint/latest/apireference_smsvoicev2/Welcome.html"
TARGET_PREFIX = "PinpointSMSVoiceV2"
SIGNING_NAME = "sms-voice"
CONTENT_TYPE = "application/x-amz-json-1.0"
# The largest MaxResults that every Describe operation accepts.
PAGE_SIZE = 100
ERROR_PREFIX = "AWS End User Messaging request failed"


@frozen
class FanOut:
    # Each parent table gives the identities, from its `id_field`, that the child request sends in `request_field`.
    parents: tuple[tuple[str, str], ...]
    request_field: str
    # The child response gives the ARN of the parent at the top level. The rows get it in `arn_column`.
    response_arn_field: str
    response_name_field: str
    arn_column: str
    name_column: str


@frozen
class Endpoint:
    operation: str
    result_key: str
    primary_keys: tuple[str, ...]
    description: str
    fan_out: FanOut | None = None


ENDPOINTS: dict[str, Endpoint] = {
    "phone_numbers": Endpoint(
        operation="DescribePhoneNumbers",
        result_key="PhoneNumbers",
        primary_keys=("phone_number_arn",),
        description="Origination phone numbers in the account, with their type, capabilities, and status.",
    ),
    "pools": Endpoint(
        operation="DescribePools",
        result_key="Pools",
        primary_keys=("pool_arn",),
        description="Pools of origination identities, with their two-way and opt-out settings.",
    ),
    "sender_ids": Endpoint(
        operation="DescribeSenderIds",
        result_key="SenderIds",
        primary_keys=("sender_id_arn",),
        description="Sender IDs in the account, with their country, message types, and registration state.",
    ),
    "configuration_sets": Endpoint(
        operation="DescribeConfigurationSets",
        result_key="ConfigurationSets",
        primary_keys=("configuration_set_arn",),
        description="Configuration sets, with their event destinations and default sending settings.",
    ),
    "opt_out_lists": Endpoint(
        operation="DescribeOptOutLists",
        result_key="OptOutLists",
        primary_keys=("opt_out_list_arn",),
        description="Opt-out lists in the account.",
    ),
    "opted_out_numbers": Endpoint(
        operation="DescribeOptedOutNumbers",
        result_key="OptedOutNumbers",
        primary_keys=("opt_out_list_arn", "opted_out_number"),
        description="Destination phone numbers in each opt-out list, with the time they opted out.",
        fan_out=FanOut(
            parents=(("opt_out_lists", "OptOutListArn"),),
            request_field="OptOutListName",
            response_arn_field="OptOutListArn",
            response_name_field="OptOutListName",
            arn_column="opt_out_list_arn",
            name_column="opt_out_list_name",
        ),
    ),
    "keywords": Endpoint(
        operation="DescribeKeywords",
        result_key="Keywords",
        primary_keys=("origination_identity_arn", "keyword"),
        description="Keywords on each phone number and pool, with the message and action for each keyword.",
        fan_out=FanOut(
            parents=(("phone_numbers", "PhoneNumberArn"), ("pools", "PoolArn")),
            request_field="OriginationIdentity",
            response_arn_field="OriginationIdentityArn",
            response_name_field="OriginationIdentity",
            arn_column="origination_identity_arn",
            name_column="origination_identity",
        ),
    ),
    "registrations": Endpoint(
        operation="DescribeRegistrations",
        result_key="Registrations",
        primary_keys=("registration_arn",),
        description="Registrations for phone numbers and sender IDs, with their type, status, and versions.",
    ),
    "verified_destination_numbers": Endpoint(
        operation="DescribeVerifiedDestinationNumbers",
        result_key="VerifiedDestinationNumbers",
        primary_keys=("verified_destination_number_arn",),
        description="Destination phone numbers that are verified for sending from a simulator or sandbox account.",
    ),
    "protect_configurations": Endpoint(
        operation="DescribeProtectConfigurations",
        result_key="ProtectConfigurations",
        primary_keys=("protect_configuration_arn",),
        description="Protect configurations that control which countries messages can go to.",
    ),
    "spend_limits": Endpoint(
        operation="DescribeSpendLimits",
        result_key="SpendLimits",
        primary_keys=("name",),
        description="Monthly spend limits for text, voice, and media messages.",
    ),
    "account_attributes": Endpoint(
        operation="DescribeAccountAttributes",
        result_key="AccountAttributes",
        primary_keys=("name",),
        description="Account attributes, such as the account tier and the default protect configuration.",
    ),
    "account_limits": Endpoint(
        operation="DescribeAccountLimits",
        result_key="AccountLimits",
        primary_keys=("name",),
        description="Account quotas, with the quantity in use and the maximum for each resource type.",
    ),
}

IAM_ACTIONS = tuple(sorted({f"sms-voice:{endpoint.operation}" for endpoint in ENDPOINTS.values()}))
PERMISSION_MESSAGE = (
    "AWS denied access. Grant the IAM user or role the sms-voice Describe actions for the tables you select, "
    "for example sms-voice:Describe*."
)
INVALID_CREDENTIALS_MESSAGE = (
    "AWS rejected the credentials. Check the access key ID, the secret access key, and the session token."
)
ERROR_MESSAGES: dict[str, str] = {
    "AccessDenied": PERMISSION_MESSAGE,
    "AccessDeniedException": PERMISSION_MESSAGE,
    "UnrecognizedClientException": INVALID_CREDENTIALS_MESSAGE,
    "InvalidClientTokenId": "AWS rejected the access key ID. Check that the key is active.",
    "InvalidSignatureException": "AWS rejected the signature. Check the secret access key and the session token.",
    "SignatureDoesNotMatch": "AWS rejected the signature. Check the secret access key.",
    "IncompleteSignature": INVALID_CREDENTIALS_MESSAGE,
    "MissingAuthenticationToken": INVALID_CREDENTIALS_MESSAGE,
    "ExpiredTokenException": "The AWS session token expired. Connect again with current credentials.",
    "ExpiredToken": "The AWS session token expired. Connect again with current credentials.",
    "OptInRequired": "Enable AWS End User Messaging SMS in this account and region, then try again.",
    "SubscriptionRequiredException": "Enable AWS End User Messaging SMS in this account and region, then try again.",
    # A bare 401 or 403 with no AWS error code in the response.
    "HTTP 401": INVALID_CREDENTIALS_MESSAGE,
    "HTTP 403": PERMISSION_MESSAGE,
}
THROTTLING_CODES = frozenset({"ThrottlingException", "Throttling", "TooManyRequestsException"})
