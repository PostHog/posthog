import re
from typing import Final

from rest_framework.exceptions import APIException

# The first release that tracks a logs alert destination by its row id. Older releases track it by
# HogFunction ids, which a destination created without HogFunctions does not have.
FIRST_ROW_ID_PROVIDER_VERSION: Final = (1, 0, 32)
LOGS_ALERT_DESTINATION_DOCS_URL: Final = (
    "https://registry.terraform.io/providers/posthog/posthog/latest/docs/resources/logs_alert_destination"
)

_PROVIDER_USER_AGENT = re.compile(r"posthog/terraform-provider; version: (\S+)")
# A local build appends `-N.gSHA` or `-dirty` to the tag it was built from, so it compares as that
# tag. A build with no tag in reach reads `v0.0.0-...` and compares as 0.0.0.
_RELEASE_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)(?:-.*)?")


class TerraformProviderUpgradeRequired(APIException):
    status_code = 400
    default_code = "terraform_provider_upgrade_required"
    # Without it, the exception handler labels an `APIException` it does not know a server error.
    default_type = "invalid_request"


def refuse_untrackable_terraform_create(user_agent: str) -> None:
    """Raises `TerraformProviderUpgradeRequired` when a Terraform provider released before
    `FIRST_ROW_ID_PROVIDER_VERSION` sends the request. A version with no number, such as `dev` or
    `test`, is a build of the provider's own checkout, so it passes."""
    match = _PROVIDER_USER_AGENT.search(user_agent)
    if match is None:
        return
    sent_version = match.group(1)
    release = _RELEASE_VERSION.fullmatch(sent_version)
    if release is None:
        return
    if tuple(int(part) for part in release.groups()) >= FIRST_ROW_ID_PROVIDER_VERSION:
        return
    first_version = ".".join(str(part) for part in FIRST_ROW_ID_PROVIDER_VERSION)
    raise TerraformProviderUpgradeRequired(
        f"This alert stores new destinations without hog functions, and PostHog Terraform provider {sent_version} "
        f"can't track them. Nothing was created. Upgrade the provider to {first_version} or later, run "
        f"terraform init -upgrade, then apply again. {LOGS_ALERT_DESTINATION_DOCS_URL}"
    )
