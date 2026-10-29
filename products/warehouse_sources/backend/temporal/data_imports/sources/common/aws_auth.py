import time
import datetime as dt
import functools
from typing import Protocol

from asgiref.sync import async_to_sync
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials, RefreshableCredentials
from botocore.exceptions import BotoCoreError, ClientError

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
# AWS sources set this as their `flat_stored_selects`, because their keys sat at the top level before `aws_auth`.
AWS_FLAT_STORED_SELECTS = frozenset({AWS_AUTH_FIELD_NAME})

MISSING_ACCESS_KEYS_ERROR = "Enter both an AWS access key ID and a secret access key."
MISSING_ROLE_ERROR = "Select an AWS connection that holds your IAM role."
ROLE_NOT_FOUND_ERROR = "The AWS connection for this source no longer exists. Select another one."
KEY_CONNECTION_FOR_ROLE_ERROR = (
    "This AWS connection holds access keys, not an IAM role. Select a role connection, or choose Access keys."
)
ROLE_UNAVAILABLE_ERROR = (
    "Connecting with an IAM role is not available on this PostHog instance. Connect with access keys instead."
)
ROLE_ACCESS_DENIED_ERROR = "PostHog could not assume your IAM role"
# Carries no AWS error code, so a source's error patterns cannot read it as a rejected customer key.
ROLE_CREDENTIALS_RETRY_ERROR = (
    "PostHog could not get credentials for your IAM role from AWS. Try again in a few minutes."
)
ROLE_EXTERNAL_ID_NOT_ENFORCED_ERROR = "Your IAM role does not require an external ID"

# Each one stays the same on every attempt until the user changes the source or the role.
# `ROLE_UNAVAILABLE_ERROR` and `ROLE_CREDENTIALS_RETRY_ERROR` are left out, because the user cannot fix
# them and the sync retries.
AWS_AUTH_NON_RETRYABLE_ERRORS: dict[str, str | None] = {
    MISSING_ACCESS_KEYS_ERROR: None,
    MISSING_ROLE_ERROR: None,
    ROLE_NOT_FOUND_ERROR: None,
    KEY_CONNECTION_FOR_ROLE_ERROR: None,
    ROLE_ACCESS_DENIED_ERROR: None,
    ROLE_EXTERNAL_ID_NOT_ENFORCED_ERROR: None,
}


# botocore's mandatory refresh window. Inside it the credentials are about to expire, so always call STS.
_MANDATORY_REFRESH_WINDOW = dt.timedelta(minutes=10)
_REFRESH_BACKOFF_SECONDS = 60


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

    The IAM role picker names batch exports' `aws-s3` connections, so the default `credential_kind`
    would be `aws-s3` for every source with this field. A source sets its own `credential_kind`, so
    that its typed-in keys keep a kind of their own.
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
                        label="Role connection",
                        kind="aws-s3",
                        required=False,
                    ),
                ],
            ),
        ],
        caption="With an IAM role, PostHog reads with short-lived credentials and stores no key. Create a role connection with your role's ARN, then grant the role the permissions listed above.",
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
        raise AwsAuthError(KEY_CONNECTION_FOR_ROLE_ERROR)
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

    expires_at: dt.datetime | None = None
    failed_at: float | None = None

    def fetch() -> dict[str, str]:
        nonlocal expires_at, failed_at
        # botocore tries a refresh on every signed request from 15 minutes before expiry, and keeps
        # the current credentials if it fails before the last 10 minutes. During an STS outage that
        # would add an STS round trip to every request, so a failed refresh waits a minute.
        if (
            failed_at is not None
            and time.monotonic() - failed_at < _REFRESH_BACKOFF_SECONDS
            and expires_at is not None
            and expires_at - dt.datetime.now(dt.UTC) > _MANDATORY_REFRESH_WINDOW
        ):
            raise AwsAuthError(ROLE_CREDENTIALS_RETRY_ERROR)
        try:
            assumed = async_to_sync(assume_role)()
        except ExternalRoleArnNotConfiguredError:
            raise AwsAuthError(ROLE_UNAVAILABLE_ERROR) from None
        except InvalidCredentialsError:
            raise AwsAuthError(
                f"{ROLE_EXTERNAL_ID_NOT_ENFORCED_ERROR}. Add a condition to its trust policy that requires the external ID {external_id}."
            ) from None
        except ClientError as e:
            # Both hops of the chain are AssumeRole calls. Only a denial that names the customer's role
            # is theirs to fix. A denial of PostHog's own role is a deployment problem, so it retries.
            error = e.response.get("Error", {})
            if error.get("Code") != "AccessDenied" or integration.aws_role_arn not in (error.get("Message") or ""):
                failed_at = time.monotonic()
                raise AwsAuthError(ROLE_CREDENTIALS_RETRY_ERROR) from e
            raise AwsAuthError(
                f"{ROLE_ACCESS_DENIED_ERROR}. Check that its trust policy allows PostHog's role and requires the external ID {external_id}."
            ) from None
        except BotoCoreError as e:
            # A connection error or a timeout before STS answered.
            failed_at = time.monotonic()
            raise AwsAuthError(ROLE_CREDENTIALS_RETRY_ERROR) from e

        assert assumed.aws_session_token and assumed.expiration
        expires_at, failed_at = assumed.expiration, None
        return {
            "access_key": assumed.aws_access_key_id,
            "secret_key": assumed.aws_secret_access_key,
            "token": assumed.aws_session_token,
            "expiry_time": assumed.expiration.isoformat(),
        }

    return RefreshableCredentials.create_from_metadata(fetch(), refresh_using=fetch, method="sts-assume-role")


def sign_aws_request(request: AWSRequest, credentials: Credentials, service: str, region: str) -> None:
    """Sign one request with a consistent snapshot of the credentials.

    Role credentials refresh, so a signer built once with them could mix the keys of two sessions.
    """
    SigV4Auth(credentials.get_frozen_credentials(), service, region).add_auth(request)


def aws_redact_values(credentials: Credentials) -> tuple[str, ...]:
    """The credential strings to mask from logged requests, taken from the current snapshot."""
    frozen = credentials.get_frozen_credentials()
    return tuple(value for value in (frozen.access_key, frozen.secret_key, frozen.token) if value)
