import functools
from typing import Protocol

from asgiref.sync import async_to_sync
from botocore.credentials import Credentials, RefreshableCredentials
from botocore.exceptions import ClientError

from posthog.models.integration import AWSS3Integration, AWSS3RoleBasedIntegration, IntegrationError
from posthog.models.team import Team

from products.warehouse_sources.backend.facade.source_config import (
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

AWS_AUTH_FIELD_NAME = "aws_auth"

MISSING_ACCESS_KEYS_ERROR = "Enter both an AWS access key ID and a secret access key."
MISSING_ROLE_ERROR = "Select an AWS connection that holds your IAM role."
ROLE_NOT_FOUND_ERROR = "The AWS connection for this source no longer exists. Select another one."
ROLE_UNAVAILABLE_ERROR = (
    "Connecting with an IAM role is not available on this PostHog instance. Connect with access keys instead."
)
ROLE_ACCESS_DENIED_ERROR = "PostHog could not assume your IAM role"
ROLE_EXTERNAL_ID_NOT_ENFORCED_ERROR = "Your IAM role does not require an external ID"

# Each one stays the same on every attempt until the user changes the source or the role.
AWS_AUTH_NON_RETRYABLE_ERRORS: dict[str, str | None] = {
    MISSING_ACCESS_KEYS_ERROR: None,
    MISSING_ROLE_ERROR: None,
    ROLE_NOT_FOUND_ERROR: None,
    ROLE_UNAVAILABLE_ERROR: None,
    ROLE_ACCESS_DENIED_ERROR: None,
    ROLE_EXTERNAL_ID_NOT_ENFORCED_ERROR: None,
}

# STS fails these on a trust policy that does not name PostHog's role or the external ID.
_ACCESS_DENIED_CODES = frozenset({"AccessDenied", "InvalidClientTokenId"})


class AwsAuthError(Exception):
    pass


class AwsAuth(Protocol):
    """The `aws_auth` block that `aws_auth_field` generates in a source config."""

    @property
    def selection(self) -> str: ...

    @property
    def aws_access_key_id(self) -> str | None: ...

    @property
    def aws_secret_access_key(self) -> str | None: ...

    @property
    def aws_session_token(self) -> str | None: ...

    @property
    def aws_integration_id(self) -> int | None: ...


def aws_auth_field() -> SourceFieldSelectConfig:
    """The choice between typed-in access keys and an IAM role from an `aws-s3` integration.

    The key fields are optional in the config so that a role config parses. `resolve_aws_credentials`
    enforces them for the access keys branch. Configs saved before this field existed hold the keys
    at the top level, and they parse into the access keys branch, which is the default.
    """
    return SourceFieldSelectConfig(
        name=AWS_AUTH_FIELD_NAME,
        label="Authentication",
        required=True,
        defaultValue="access_keys",
        options=[
            SourceFieldSelectConfigOption(
                label="Access keys",
                value="access_keys",
                fields=[
                    SourceFieldInputConfig(
                        name="aws_access_key_id",
                        label="AWS access key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="AKIA...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="aws_secret_access_key",
                        label="AWS secret access key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="aws_session_token",
                        label="AWS session token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="Only needed for temporary credentials",
                        caption="Only for temporary credentials. Session tokens expire after a few hours, so scheduled syncs fail once the token expires. Use a permanent access key (starts with AKIA) or an IAM role for recurring imports.",
                        secret=True,
                    ),
                ],
            ),
            SourceFieldSelectConfigOption(
                label="IAM role",
                value="role",
                fields=[
                    SourceFieldOauthConfig(
                        name="aws_integration_id",
                        label="AWS connection",
                        kind="aws-s3",
                        required=False,
                    ),
                ],
            ),
        ],
        caption="With an IAM role, PostHog reads with short-lived credentials and stores no key. Create an AWS connection with your role's ARN, then grant the role the permissions listed above.",
    )


def resolve_aws_credentials(auth: AwsAuth, team_id: int) -> Credentials:
    """The credentials to sign the source's AWS requests with.

    A role gives refreshable credentials. The second hop of the role chain caps a session at one
    hour, so botocore assumes the role again when the credentials are about to expire.
    """
    if auth.selection != "role":
        if not auth.aws_access_key_id or not auth.aws_secret_access_key:
            raise AwsAuthError(MISSING_ACCESS_KEYS_ERROR)
        return Credentials(auth.aws_access_key_id, auth.aws_secret_access_key, auth.aws_session_token or None)

    if not auth.aws_integration_id:
        raise AwsAuthError(MISSING_ROLE_ERROR)
    return _integration_credentials(auth.aws_integration_id, team_id)


def _integration_credentials(integration_id: int, team_id: int) -> Credentials:
    # Importing the batch exports facade loads aioboto3, so it stays off the source registry's import path.
    from products.batch_exports.backend.facade.destinations.s3 import (  # noqa: PLC0415
        ExternalRoleArnNotConfiguredError,
        InvalidCredentialsError,
        PolicyStatement,
        S3IntegrationNotFoundError,
        get_credentials_using_user_aws_role,
        get_s3_integration,
    )

    try:
        integration = async_to_sync(get_s3_integration)(integration_id, team_id)
    except (S3IntegrationNotFoundError, IntegrationError):
        raise AwsAuthError(ROLE_NOT_FOUND_ERROR) from None

    if isinstance(integration, AWSS3Integration):
        return Credentials(integration.aws_access_key_id, integration.aws_secret_access_key)
    # An S3-compatible connection holds keys for another provider, which AWS does not accept.
    if not isinstance(integration, AWSS3RoleBasedIntegration):
        raise AwsAuthError(ROLE_NOT_FOUND_ERROR)

    # The external ID is derived from the source's organization on every call, never read from
    # config, so one organization cannot use a role that trusts another organization.
    organization_id = Team.objects.only("organization_id").get(id=team_id).organization_id
    external_id = f"posthog-{organization_id}"
    assume_role = functools.partial(
        get_credentials_using_user_aws_role,
        integration.aws_role_arn,
        external_id,
        session_name=f"PostHog-warehouse-source-{team_id}",
        # The customer's role decides what PostHog can read. A source calls several services, so a
        # narrower session policy per source would only break reads that the role allows.
        policy_statements=[PolicyStatement(Effect="Allow", Action=["*"], Resource="*")],
        # Without a retry an STS hiccup fails the sync. With the default five attempts, a role that
        # denies PostHog keeps the credential check waiting for half a minute.
        max_attempts=2,
    )

    def fetch() -> dict[str, str]:
        try:
            assumed = async_to_sync(assume_role)()
        except ExternalRoleArnNotConfiguredError:
            raise AwsAuthError(ROLE_UNAVAILABLE_ERROR) from None
        except InvalidCredentialsError:
            raise AwsAuthError(
                f"{ROLE_EXTERNAL_ID_NOT_ENFORCED_ERROR}. Add a condition to its trust policy that requires the external ID {external_id}."
            ) from None
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") not in _ACCESS_DENIED_CODES:
                raise
            raise AwsAuthError(
                f"{ROLE_ACCESS_DENIED_ERROR}. Check that its trust policy allows PostHog's role and requires the external ID {external_id}."
            ) from None

        assert assumed.aws_session_token and assumed.expiration
        return {
            "access_key": assumed.aws_access_key_id,
            "secret_key": assumed.aws_secret_access_key,
            "token": assumed.aws_session_token,
            "expiry_time": assumed.expiration.isoformat(),
        }

    return RefreshableCredentials.create_from_metadata(fetch(), refresh_using=fetch, method="sts-assume-role")
