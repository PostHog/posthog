import datetime as dt
from dataclasses import dataclass

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from botocore.awsrequest import AWSRequest
from botocore.credentials import RefreshableCredentials
from botocore.exceptions import ClientError, EndpointConnectionError
from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team import Team

from products.batch_exports.backend.facade.contracts import AWSCredentials
from products.batch_exports.backend.facade.destinations.s3 import (
    ExternalRoleArnNotConfiguredError,
    InvalidCredentialsError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.aws_auth import (
    AWS_AUTH_NON_RETRYABLE_ERRORS,
    KEY_CONNECTION_FOR_ROLE_ERROR,
    ROLE_ACCESS_DENIED_ERROR,
    ROLE_CREDENTIALS_RETRY_ERROR,
    ROLE_EXTERNAL_ID_NOT_ENFORCED_ERROR,
    ROLE_NOT_FOUND_ERROR,
    ROLE_UNAVAILABLE_ERROR,
    AwsAuthError,
    resolve_aws_credentials,
    sign_aws_request,
)

ROLE_ARN = "arn:aws:iam::123456789012:role/posthog-reader"
ASSUME_ROLE = "products.batch_exports.backend.facade.destinations.s3.get_credentials_using_user_aws_role"


@dataclass(frozen=True)
class Auth:
    selection: str = "role"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    aws_integration_id: int | None = None


def assumed(suffix: str, expires_in: dt.timedelta) -> AWSCredentials:
    return AWSCredentials(
        aws_access_key_id=f"ASIA{suffix}",
        aws_secret_access_key=f"secret-{suffix}",
        aws_session_token=f"token-{suffix}",
        expiration=dt.datetime.now(dt.UTC) + expires_in,
    )


class TestResolveAwsCredentials(BaseTest):
    def _integration(self, team: Team, kind: str = "aws-s3", **config: str) -> Integration:
        return Integration.objects.create(
            team=team,
            kind=kind,
            integration_id=config.get("name", "reader"),
            config={"name": "reader", **config},
            sensitive_config={},
        )

    def test_role_assumes_with_the_source_organizations_external_id_and_refreshes(self) -> None:
        integration = self._integration(self.team, aws_role_arn=ROLE_ARN)
        assume = AsyncMock(
            side_effect=[assumed("FIRST", dt.timedelta(minutes=5)), assumed("SECOND", dt.timedelta(hours=1))]
        )

        with patch(ASSUME_ROLE, assume):
            credentials = resolve_aws_credentials(Auth(aws_integration_id=integration.id), self.team.id)
            frozen = credentials.get_frozen_credentials()

        assert frozen.access_key == "ASIASECOND"
        assert frozen.token == "token-SECOND"
        assert assume.call_count == 2
        assert assume.call_args.args == (ROLE_ARN, f"posthog-{self.team.organization_id}")

    def test_access_key_connection_under_the_role_option_is_refused(self) -> None:
        integration = self._integration(self.team)
        integration.sensitive_config = {"aws_access_key_id": "AKIASTORED", "aws_secret_access_key": "stored"}
        integration.save()

        with patch(ASSUME_ROLE) as assume, self.assertRaisesMessage(AwsAuthError, KEY_CONNECTION_FOR_ROLE_ERROR):
            resolve_aws_credentials(Auth(aws_integration_id=integration.id), self.team.id)
        assume.assert_not_called()

    @parameterized.expand(["other_team", "s3_compatible", "github", "deleted"])
    def test_connection_the_source_cannot_use_is_not_found(self, case: str) -> None:
        if case == "other_team":
            other_team = Team.objects.create(organization=Organization.objects.create(name="other"))
            integration_id = self._integration(other_team, aws_role_arn=ROLE_ARN).id
        elif case == "s3_compatible":
            integration_id = self._integration(self.team, kind="s3-compatible", endpoint_url="https://example.com").id
        elif case == "github":
            integration_id = self._integration(self.team, kind="github").id
        else:
            integration_id = 999999

        with patch(ASSUME_ROLE) as assume, self.assertRaisesMessage(AwsAuthError, ROLE_NOT_FOUND_ERROR):
            resolve_aws_credentials(Auth(aws_integration_id=integration_id), self.team.id)
        assume.assert_not_called()

    @parameterized.expand(
        [
            (
                ClientError(
                    {
                        "Error": {
                            "Code": "AccessDenied",
                            "Message": f"not authorized to perform: sts:AssumeRole on resource: {ROLE_ARN}",
                        }
                    },
                    "AssumeRole",
                ),
                ROLE_ACCESS_DENIED_ERROR,
            ),
            (InvalidCredentialsError(), ROLE_EXTERNAL_ID_NOT_ENFORCED_ERROR),
            (ExternalRoleArnNotConfiguredError(), ROLE_UNAVAILABLE_ERROR),
        ]
    )
    def test_role_failures_raise_a_stable_message(self, error: Exception, message: str) -> None:
        integration = self._integration(self.team, aws_role_arn=ROLE_ARN)

        with patch(ASSUME_ROLE, side_effect=error), self.assertRaisesMessage(AwsAuthError, message):
            resolve_aws_credentials(Auth(aws_integration_id=integration.id), self.team.id)

    @parameterized.expand(
        [
            ("throttled", "Throttling", ""),
            (
                "posthog_credentials_rejected",
                "InvalidClientTokenId",
                "The security token included in the request is invalid.",
            ),
            (
                "posthog_role_denied",
                "AccessDenied",
                "not authorized to perform: sts:AssumeRole on resource: arn:aws:iam::000000000000:role/posthog-external",
            ),
        ]
    )
    def test_failure_the_user_cannot_fix_retries_without_the_aws_code(
        self, _name: str, code: str, message: str
    ) -> None:
        integration = self._integration(self.team, aws_role_arn=ROLE_ARN)

        with (
            patch(ASSUME_ROLE, side_effect=ClientError({"Error": {"Code": code, "Message": message}}, "AssumeRole")),
            self.assertRaises(AwsAuthError) as raised,
        ):
            resolve_aws_credentials(Auth(aws_integration_id=integration.id), self.team.id)

        assert str(raised.exception) == ROLE_CREDENTIALS_RETRY_ERROR
        assert ROLE_CREDENTIALS_RETRY_ERROR not in AWS_AUTH_NON_RETRYABLE_ERRORS

    @parameterized.expand(
        [
            ("throttled", ClientError({"Error": {"Code": "Throttling", "Message": ""}}, "AssumeRole")),
            ("unreachable", EndpointConnectionError(endpoint_url="https://sts.amazonaws.com")),
        ]
    )
    def test_failed_advisory_refresh_waits_before_calling_sts_again(self, _name: str, failure: Exception) -> None:
        integration = self._integration(self.team, aws_role_arn=ROLE_ARN)
        assume = AsyncMock(side_effect=[assumed("FIRST", dt.timedelta(minutes=12)), failure, failure])

        with patch(ASSUME_ROLE, assume):
            credentials = resolve_aws_credentials(Auth(aws_integration_id=integration.id), self.team.id)
            first = credentials.get_frozen_credentials()
            second = credentials.get_frozen_credentials()

        assert first.access_key == second.access_key == "ASIAFIRST"
        assert assume.call_count == 2


def _expiry(**delta: int) -> str:
    return (dt.datetime.now(dt.UTC) + dt.timedelta(**delta)).isoformat()


def test_sign_aws_request_signs_with_the_refreshed_role_session() -> None:
    sessions = iter(
        [
            {"access_key": "ASIAFIRST", "secret_key": "s1", "token": "t1", "expiry_time": _expiry(minutes=5)},
            {"access_key": "ASIASECOND", "secret_key": "s2", "token": "t2", "expiry_time": _expiry(hours=1)},
        ]
    )
    credentials = RefreshableCredentials.create_from_metadata(
        next(sessions), refresh_using=lambda: next(sessions), method="sts-assume-role"
    )
    request = AWSRequest(method="POST", url="https://config.us-east-1.amazonaws.com/", data=b"{}")

    sign_aws_request(request, credentials, "config", "us-east-1")

    assert "Credential=ASIASECOND/" in request.headers["Authorization"]
    assert request.headers["X-Amz-Security-Token"] == "t2"
