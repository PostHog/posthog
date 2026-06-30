import re

from posthog.hogql.errors import ExposedHogQLError

# A Snowflake account identifier is either the org-account form (`orgname-account_name`)
# or the legacy dotted form (`account.region.cloud`) — letters, digits, hyphens,
# underscores, and dots only. Rejecting anything else keeps a crafted value from
# steering the connector at an arbitrary host.
_SNOWFLAKE_ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_snowflake_account_id(account_id: str | None) -> str:
    candidate = (account_id or "").strip()
    if not candidate or not _SNOWFLAKE_ACCOUNT_ID_RE.fullmatch(candidate):
        raise ExposedHogQLError("Invalid Snowflake account identifier.")
    return candidate
