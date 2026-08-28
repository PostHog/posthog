import re
from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# SES is a regional service: the user-configured region is interpolated into both the request
# host and the SigV4 signing scope.
SES_ENDPOINT_TEMPLATE = "https://email.{region}.amazonaws.com"
SES_SIGNING_NAME = "ses"
REGION_PATTERN = re.compile(r"^[a-z0-9-]+$")

REQUEST_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class AwsSesEndpointConfig:
    name: str
    # Path of the operation that produces this table's rows (a list path, or the object path
    # for single-row endpoints).
    path: str
    primary_key: list[str] | None
    # Response key holding the list of items. `None` for single-object endpoints, where the
    # whole response body is the row.
    result_key: str | None = None
    # `PageSize` per request. `None` for unpaginated single-object endpoints.
    page_size: int | None = None
    # Fan-out: per-item GET path with a `{name}` placeholder. The list call only returns
    # summaries (or bare names), so each item is fetched individually for the full row.
    detail_path: str | None = None
    # Fan-out: key of the item's name in the list response. `None` when list items are plain
    # name strings (ListConfigurationSets).
    item_name_key: str | None = None
    # Fan-out: column carrying the item name. Set explicitly on every row because detail
    # responses (GetEmailIdentity) do not echo the name back.
    name_column: str | None = None
    # ListSuppressedDestinations accepts a server-side `StartDate` filter, which is what makes
    # that endpoint genuinely incremental.
    supports_start_date: bool = False
    # Flattened columns holding epoch-seconds timestamps, parsed into datetimes.
    timestamp_columns: tuple[str, ...] = ()
    # Response members that are maps with caller-defined keys (e.g. `Policies`). Flattening
    # them would mint one column per map entry, so they are kept whole and stored as JSON.
    raw_keys: frozenset[str] = field(default_factory=frozenset)


AWS_SES_ENDPOINTS: dict[str, AwsSesEndpointConfig] = {
    "account": AwsSesEndpointConfig(
        name="account",
        path="/v2/email/account",
        primary_key=None,
    ),
    "configuration_sets": AwsSesEndpointConfig(
        name="configuration_sets",
        path="/v2/email/configuration-sets",
        primary_key=["configuration_set_name"],
        result_key="ConfigurationSets",
        page_size=100,
        detail_path="/v2/email/configuration-sets/{name}",
        name_column="configuration_set_name",
        timestamp_columns=("reputation_options_last_fresh_start",),
    ),
    "email_identities": AwsSesEndpointConfig(
        name="email_identities",
        path="/v2/email/identities",
        primary_key=["identity_name"],
        result_key="EmailIdentities",
        page_size=100,
        detail_path="/v2/email/identities/{name}",
        item_name_key="IdentityName",
        name_column="identity_name",
        timestamp_columns=(
            "dkim_attributes_last_key_generation_timestamp",
            "verification_info_last_checked_timestamp",
            "verification_info_last_success_timestamp",
        ),
        raw_keys=frozenset({"Policies"}),
    ),
    "suppressed_destinations": AwsSesEndpointConfig(
        name="suppressed_destinations",
        path="/v2/email/suppression/addresses",
        primary_key=["email_address"],
        result_key="SuppressedDestinationSummaries",
        page_size=1000,
        supports_start_date=True,
        timestamp_columns=("last_update_time",),
    ),
}

ENDPOINTS = tuple(AWS_SES_ENDPOINTS.keys())

# Only the suppression list has a server-side time filter (`StartDate` on `LastUpdateTime`).
# The other endpoints have no filter at all, so they stay full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "suppressed_destinations": [
        {
            "label": "last_update_time",
            "type": IncrementalFieldType.DateTime,
            "field": "last_update_time",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "account": "Sending status, quota, and reputation enforcement for the connected AWS Region. One row per sync.",
    "configuration_sets": "Configuration sets with their tracking, delivery, reputation, sending, and suppression options.",
    "email_identities": "Verified email identities (domains and addresses) with DKIM, MAIL FROM, and verification details.",
    "suppressed_destinations": "Email addresses on the account-level suppression list, with the reason and time they were added.",
}
