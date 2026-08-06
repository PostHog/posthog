from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# SESv2 is regional and reached over its REST/JSON interface at email.{region}.amazonaws.com.
# SigV4 signs with the "ses" service name (shared by the v1 and v2 SES APIs).
SES_HOST_TEMPLATE = "email.{region}.amazonaws.com"
SES_SIGNING_NAME = "ses"
SES_DEFAULT_REGION = "us-east-1"

# SESv2 caps list responses at 1000 per page for the endpoints this source reads.
DEFAULT_PAGE_SIZE = 1000

# An address stays on the suppression list until it is manually removed, but its
# LastUpdateTime moves each time SES re-suppresses it. An incremental run rewinds this far
# behind the stored watermark so a re-suppression that lands just after a sync is picked up.
SUPPRESSION_RESTATEMENT_LOOKBACK_DAYS = 2


@dataclass(frozen=True)
class SesEndpointConfig:
    name: str
    # SESv2 operation name, used for logging and error messages only.
    operation: str
    # Request path under the regional host, e.g. `/v2/email/account`.
    path: str
    primary_key: list[str] | None
    # Response key holding the list of rows. `None` for GetAccount, which returns a single
    # object that becomes one row.
    result_key: str | None = None
    # SESv2 paginates every list endpoint this source reads with a `NextToken` cursor.
    paginated: bool = True
    # Some list endpoints return bare strings (ListConfigurationSets returns names). When set,
    # each string becomes a one-column row under this name instead of being flattened.
    string_list_column: str | None = None
    # Only ListSuppressedDestinations exposes a server-side timestamp filter (StartDate), so it
    # is the only endpoint that can sync incrementally.
    incremental: bool = False
    incremental_field: str | None = None


AWS_SES_ENDPOINTS: dict[str, SesEndpointConfig] = {
    "account": SesEndpointConfig(
        name="account",
        operation="GetAccount",
        path="/v2/email/account",
        result_key=None,
        primary_key=None,
        paginated=False,
    ),
    "configuration_sets": SesEndpointConfig(
        name="configuration_sets",
        operation="ListConfigurationSets",
        path="/v2/email/configuration-sets",
        result_key="ConfigurationSets",
        primary_key=["configuration_set_name"],
        string_list_column="configuration_set_name",
    ),
    "email_identities": SesEndpointConfig(
        name="email_identities",
        operation="ListEmailIdentities",
        path="/v2/email/identities",
        result_key="EmailIdentities",
        primary_key=["identity_name"],
    ),
    "suppressed_destinations": SesEndpointConfig(
        name="suppressed_destinations",
        operation="ListSuppressedDestinations",
        path="/v2/email/suppression/addresses",
        result_key="SuppressedDestinationSummaries",
        primary_key=["email_address"],
        incremental=True,
        incremental_field="last_update_time",
    ),
}

ENDPOINTS = tuple(AWS_SES_ENDPOINTS.keys())

# Only the suppression list can filter server-side (StartDate on LastUpdateTime); every other
# endpoint returns current state in full, so it has no honest incremental cursor.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: (
        [
            {
                "label": endpoint.incremental_field,
                "type": IncrementalFieldType.DateTime,
                "field": endpoint.incremental_field,
                "field_type": IncrementalFieldType.DateTime,
            }
        ]
        if endpoint.incremental and endpoint.incremental_field
        else []
    )
    for name, endpoint in AWS_SES_ENDPOINTS.items()
}

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "account": "Account-level sending status, quota, and enforcement for the AWS region.",
    "configuration_sets": "Configuration sets defined in the account, used to group sending rules.",
    "email_identities": "Verified email addresses and domains, with their verification and sending status.",
    "suppressed_destinations": "Addresses on the account suppression list, with the reason they were suppressed.",
}
