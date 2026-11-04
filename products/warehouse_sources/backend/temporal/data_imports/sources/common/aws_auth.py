import json
import time
import secrets
import datetime as dt
from collections.abc import Sequence
from typing import Any, Protocol

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config
from botocore.credentials import Credentials, RefreshableCredentials
from botocore.exceptions import BotoCoreError, ClientError

from posthog.integrations import IntegrationKind, IntegrationManager, IntegrationNotFound
from posthog.models.integration import AWSWarehouseSourcesRoleBasedIntegration, IntegrationError
from posthog.models.team import Team

from products.warehouse_sources.backend.facade.source_config import (
    SourceFieldConfig,
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
UNKNOWN_AUTH_ERROR = "Choose how PostHog connects to AWS: with access keys or with an IAM role."
MISSING_ROLE_ERROR = "Select an AWS connection that holds your IAM role."
ROLE_NOT_FOUND_ERROR = "The AWS connection for this source no longer exists. Select another one."
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
    UNKNOWN_AUTH_ERROR: None,
    MISSING_ROLE_ERROR: None,
    ROLE_NOT_FOUND_ERROR: None,
    ROLE_ACCESS_DENIED_ERROR: None,
    ROLE_EXTERNAL_ID_NOT_ENFORCED_ERROR: None,
}


# botocore's mandatory refresh window. Inside it the credentials are about to expire, so always call STS.
_MANDATORY_REFRESH_WINDOW = dt.timedelta(minutes=10)
_REFRESH_BACKOFF_SECONDS = 60
# One retry absorbs an STS hiccup. A denial is not retried, so a role that refuses PostHog fails fast.
_STS_CONFIG = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2, "mode": "standard"})


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


class RoleCredentials(RefreshableCredentials):
    """Credentials of an assumed IAM role, which botocore refreshes before they expire."""

    def metadata(self) -> dict[str, str]:
        """The current credentials and their expiry, refreshed first if they are about to expire.

        Clients that keep their own credential object, such as aiobotocore under s3fs, build it from
        this so that they refresh on the same schedule.
        """
        self.get_frozen_credentials()
        # botocore swaps the keys and the expiry under this lock, so read them together, or a refresh
        # on another thread can pair old keys with a new expiry. Its type stubs leave both attributes out.
        with self._refresh_lock:  # type: ignore[attr-defined]
            frozen = self._frozen_credentials  # type: ignore[attr-defined]
            expiry_time = self._expiry_time  # type: ignore[attr-defined]
        assert frozen.access_key and frozen.secret_key and frozen.token
        return {
            "access_key": frozen.access_key,
            "secret_key": frozen.secret_key,
            "token": frozen.token,
            "expiry_time": expiry_time.isoformat(),
        }


def aws_auth_field(
    *,
    access_key_id_name: str = "aws_access_key_id",
    secret_access_key_name: str = "aws_secret_access_key",
    session_token: bool = True,
) -> SourceFieldSelectConfig:
    """The choice between typed-in access keys and an IAM role from an `aws-warehouse-sources` integration.

    The key fields are optional in the config so that a role config parses. `resolve_aws_credentials`
    enforces them for the access keys branch. Configs saved before this field existed hold the keys
    at the top level, and they parse into the access keys branch, which is the default. A source
    passes the key names it stored before the field existed, so that those configs still lift.

    The IAM role picker names the `aws-warehouse-sources` kind, so the default `credential_kind` would
    be that kind for every source with this field. A source sets its own `credential_kind`, so that its
    typed-in keys keep a kind of their own.
    """
    key_fields: list[SourceFieldConfig] = [
        SourceFieldInputConfig(
            name=access_key_id_name,
            label="AWS access key ID",
            type=SourceFieldInputConfigType.TEXT,
            required=False,
            placeholder="AKIA...",
            secret=False,
        ),
        SourceFieldInputConfig(
            name=secret_access_key_name,
            label="AWS secret access key",
            type=SourceFieldInputConfigType.PASSWORD,
            required=False,
            placeholder="",
            secret=True,
        ),
    ]
    if session_token:
        key_fields.append(
            SourceFieldInputConfig(
                name="aws_session_token",
                label="AWS session token",
                type=SourceFieldInputConfigType.PASSWORD,
                required=False,
                placeholder="Only needed for temporary credentials",
                caption="Only for temporary credentials. Session tokens expire after a few hours, so scheduled syncs fail once the token expires. Use a permanent access key (starts with AKIA) or an IAM role for recurring imports.",
                secret=True,
            )
        )
    return SourceFieldSelectConfig(
        name=AWS_AUTH_FIELD_NAME,
        label="Authentication",
        required=True,
        defaultValue="access_keys",
        options=[
            SourceFieldSelectConfigOption(
                label="Access keys",
                value="access_keys",
                fields=key_fields,
            ),
            SourceFieldSelectConfigOption(
                label="IAM role",
                value="role",
                fields=[
                    SourceFieldOauthConfig(
                        name="aws_integration_id",
                        label="Role connection",
                        kind="aws-warehouse-sources",
                        required=False,
                    ),
                ],
            ),
        ],
        caption="With an IAM role, PostHog reads with short-lived credentials and stores no key. Create a role connection with your role's ARN, then grant the role the permissions listed above.",
    )


def resolve_aws_credentials(auth: AwsAuth, team_id: int, session_actions: Sequence[str]) -> Credentials:
    """The credentials to sign the source's AWS requests with.

    `session_actions` are the IAM actions the source calls. A role session can use only those.

    A role gives refreshable credentials. The second hop of the role chain caps a session at one
    hour, so botocore assumes the role again when the credentials are about to expire.
    """
    if auth.selection == "access_keys":
        if not auth.aws_access_key_id or not auth.aws_secret_access_key:
            raise AwsAuthError(MISSING_ACCESS_KEYS_ERROR)
        return Credentials(auth.aws_access_key_id, auth.aws_secret_access_key, auth.aws_session_token or None)

    if auth.selection != "role":
        raise AwsAuthError(UNKNOWN_AUTH_ERROR)
    if not auth.aws_integration_id:
        raise AwsAuthError(MISSING_ROLE_ERROR)
    return _integration_credentials(auth.aws_integration_id, team_id, session_actions)


def session_policy(session_actions: Sequence[str]) -> str:
    """The session policy that limits a role session to `session_actions`.

    KMS actions apply only through the other services the source calls, so the session cannot decrypt
    data directly with KMS.
    """
    kms = [action for action in session_actions if action.startswith("kms:")]
    others = [action for action in session_actions if not action.startswith("kms:")]
    statements: list[dict[str, Any]] = [{"Effect": "Allow", "Action": others, "Resource": "*"}]
    if kms:
        services = sorted({action.split(":")[0] for action in others})
        statements.append(
            {
                "Effect": "Allow",
                "Action": kms,
                "Resource": "*",
                "Condition": {"StringLike": {"kms:ViaService": [f"{service}.*.amazonaws.com" for service in services]}},
            }
        )
    return json.dumps({"Version": "2012-10-17", "Statement": statements})


def _integration_credentials(integration_id: int, team_id: int, session_actions: Sequence[str]) -> Credentials:
    try:
        integration = IntegrationManager.any.get(team_id, integration_id)
    except IntegrationNotFound:
        raise AwsAuthError(ROLE_NOT_FOUND_ERROR) from None
    aws_role_arn = integration.config.get("aws_role_arn")
    if integration.kind != IntegrationKind.AWS_WAREHOUSE_SOURCES or not aws_role_arn:
        raise AwsAuthError(ROLE_NOT_FOUND_ERROR)

    # The external ID is derived from the source's organization on every call, never read from
    # config, so one organization cannot use a role that trusts another organization.
    organization_id = Team.objects.only("organization_id").get(id=team_id).organization_id
    external_id = f"posthog-{organization_id}"
    session_name = f"PostHog-warehouse-source-{team_id}"
    policy = session_policy(session_actions)

    def assume_customer_role() -> dict[str, Any]:
        import boto3  # noqa: PLC0415 — keeps boto3 off the source registry's import path

        try:
            our_role_arn = AWSWarehouseSourcesRoleBasedIntegration.our_aws_role_arn()
        except IntegrationError:
            raise AwsAuthError(ROLE_UNAVAILABLE_ERROR) from None
        try:
            ours = boto3.client("sts", config=_STS_CONFIG).assume_role(
                RoleArn=our_role_arn,
                RoleSessionName=session_name,
                # This session can do nothing but assume the customer's role.
                Policy=json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": [{"Effect": "Allow", "Action": ["sts:AssumeRole"], "Resource": aws_role_arn}],
                    }
                ),
            )["Credentials"]
        except (BotoCoreError, ClientError) as e:
            # A failure of PostHog's own role is a deployment problem, so it retries.
            raise AwsAuthError(ROLE_CREDENTIALS_RETRY_ERROR) from e

        sts = boto3.client(
            "sts",
            config=_STS_CONFIG,
            aws_access_key_id=ours["AccessKeyId"],
            aws_secret_access_key=ours["SecretAccessKey"],
            aws_session_token=ours["SessionToken"],
        )
        try:
            # A role that accepts a random external ID would let any PostHog organization use it.
            sts.assume_role(
                RoleArn=aws_role_arn, RoleSessionName=session_name, ExternalId=f"posthog-{secrets.token_hex(16)}"
            )
        except ClientError as e:
            # Only a denial proves the role checks the external ID. Any other failure proves nothing.
            if e.response.get("Error", {}).get("Code") != "AccessDenied":
                raise AwsAuthError(ROLE_CREDENTIALS_RETRY_ERROR) from e
        except BotoCoreError as e:
            raise AwsAuthError(ROLE_CREDENTIALS_RETRY_ERROR) from e
        else:
            raise AwsAuthError(
                f"{ROLE_EXTERNAL_ID_NOT_ENFORCED_ERROR}. Add a condition to its trust policy that requires the external ID {external_id}."
            )

        try:
            return sts.assume_role(
                RoleArn=aws_role_arn, RoleSessionName=session_name, ExternalId=external_id, Policy=policy
            )["Credentials"]
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "AccessDenied":
                raise AwsAuthError(ROLE_CREDENTIALS_RETRY_ERROR) from e
            raise AwsAuthError(
                f"{ROLE_ACCESS_DENIED_ERROR}. Check that its trust policy allows PostHog's role and requires the external ID {external_id}."
            ) from None
        except BotoCoreError as e:
            raise AwsAuthError(ROLE_CREDENTIALS_RETRY_ERROR) from e

    expires_at: dt.datetime | None = None
    current: dict[str, str] | None = None
    last_failure: float | None = None

    def assume() -> dict[str, str]:
        nonlocal expires_at
        assumed = assume_customer_role()
        expires_at = assumed["Expiration"]
        return {
            "access_key": assumed["AccessKeyId"],
            "secret_key": assumed["SecretAccessKey"],
            "token": assumed["SessionToken"],
            "expiry_time": assumed["Expiration"].isoformat(),
        }

    def fetch() -> dict[str, str]:
        nonlocal current, last_failure
        # botocore tries a refresh on every signed request from 15 minutes before expiry, and keeps
        # the current credentials if it fails before the last 10 minutes. After a failed refresh the
        # current credentials come back for a minute without an STS call, so that an STS outage or a
        # changed trust policy does not add an STS round trip and a logged traceback to every request.
        if (
            current is not None
            and last_failure is not None
            and time.monotonic() - last_failure < _REFRESH_BACKOFF_SECONDS
            and expires_at is not None
            and expires_at - dt.datetime.now(dt.UTC) > _MANDATORY_REFRESH_WINDOW
        ):
            return current
        try:
            current = assume()
        except AwsAuthError:
            last_failure = time.monotonic()
            raise
        last_failure = None
        return current

    return RoleCredentials.create_from_metadata(fetch(), refresh_using=fetch, method="sts-assume-role")


def aws_auth_endpoint_reasons(error: AwsAuthError, endpoints: list[str]) -> dict[str, str | None]:
    """Per-table reasons for `get_endpoint_permissions` when the credentials could not be resolved.

    Only an error the user must fix blocks the tables. A temporary one leaves them unjudged, so a brief
    STS failure does not hide every table from the picker.
    """
    message = str(error)
    reason = message if any(pattern in message for pattern in AWS_AUTH_NON_RETRYABLE_ERRORS) else None
    return dict.fromkeys(endpoints, reason)


def sign_aws_request(request: AWSRequest, credentials: Credentials, service: str, region: str) -> None:
    """Sign one request with a consistent snapshot of the credentials.

    Role credentials refresh, so a signer built once with them could mix the keys of two sessions.
    """
    SigV4Auth(credentials.get_frozen_credentials(), service, region).add_auth(request)


def aws_redact_values(credentials: Credentials) -> tuple[str, ...]:
    """The credential strings to mask from logged requests, taken from the current snapshot."""
    frozen = credentials.get_frozen_credentials()
    return tuple(value for value in (frozen.access_key, frozen.secret_key, frozen.token) if value)
