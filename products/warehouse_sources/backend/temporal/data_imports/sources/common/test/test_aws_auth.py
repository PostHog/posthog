import json
import datetime as dt
from dataclasses import dataclass
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials, RefreshableCredentials
from botocore.exceptions import ClientError, EndpointConnectionError
from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team import Team

from products.warehouse_sources.backend.temporal.data_imports.sources.common.aws_auth import (
    AWS_AUTH_FIELD_NAME,
    MISSING_ROLE_ERROR,
    ROLE_ACCESS_DENIED_ERROR,
    ROLE_CREDENTIALS_RETRY_ERROR,
    ROLE_EXTERNAL_ID_NOT_ENFORCED_ERROR,
    ROLE_NOT_FOUND_ERROR,
    ROLE_UNAVAILABLE_ERROR,
    AwsAuthError,
    aws_auth_endpoint_reasons,
    resolve_aws_credentials,
    sign_aws_request,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

ROLE_ARN = "arn:aws:iam::123456789012:role/posthog-reader"
OUR_ROLE_ARN = "arn:aws:iam::000000000000:role/posthog-external-warehouse-sources"
SESSION_ACTIONS = ("config:Describe*", "config:Get*")
# A source calls only these verbs, apart from the actions listed per source in NON_READ_ACTIONS.
READ_VERBS = ("BatchGet", "Describe", "Filter", "Get", "List", "Lookup", "Scan", "Select", "View")
NON_READ_ACTIONS: dict[ExternalDataSourceType, set[str]] = {
    # Athena runs the query as the caller and writes its results to the workgroup's S3 location.
    ExternalDataSourceType.AWSATHENA: {
        "athena:StartQueryExecution",
        "athena:StopQueryExecution",
        "kms:GenerateDataKey",
        "s3:AbortMultipartUpload",
        "s3:PutObject",
    },
}


@dataclass(frozen=True)
class Auth:
    selection: str = "role"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    aws_integration_id: int | None = None


def sts_error(code: str, message: str = "") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, "AssumeRole")


def session(suffix: str, expires_in: dt.timedelta = dt.timedelta(hours=1)) -> dict[str, Any]:
    return {
        "Credentials": {
            "AccessKeyId": f"ASIA{suffix}",
            "SecretAccessKey": f"secret-{suffix}",
            "SessionToken": f"token-{suffix}",
            "Expiration": dt.datetime.now(dt.UTC) + expires_in,
        }
    }


def chain(customer: Any) -> list[Any]:
    """STS answers for one assume: PostHog's role, the random external ID probe, then the customer's role."""
    return [session("OURS"), sts_error("AccessDenied"), customer]


def sts(*answers: Any) -> MagicMock:
    client = MagicMock()
    client.return_value.assume_role.side_effect = list(answers)
    return client


@override_settings(WAREHOUSE_SOURCES_AWS_ROLE_ARN=OUR_ROLE_ARN)
class TestResolveAwsCredentials(BaseTest):
    def _integration(self, team: Team, kind: str = "aws-warehouse-sources", **config: str) -> Integration:
        return Integration.objects.create(
            team=team,
            kind=kind,
            integration_id=config.get("name", "reader"),
            config={"name": "reader", **config},
            sensitive_config={},
        )

    def _resolve(self, client: MagicMock, integration_id: int) -> Credentials:
        with patch("boto3.client", client):
            return resolve_aws_credentials(Auth(aws_integration_id=integration_id), self.team.id, SESSION_ACTIONS)

    def test_role_assumes_through_our_role_with_the_source_organizations_external_id_and_refreshes(self) -> None:
        integration = self._integration(self.team, aws_role_arn=ROLE_ARN)
        client = sts(*chain(session("FIRST", dt.timedelta(minutes=5))), *chain(session("SECOND")))

        with patch("boto3.client", client):
            credentials = resolve_aws_credentials(
                Auth(aws_integration_id=integration.id), self.team.id, SESSION_ACTIONS
            )
            frozen = credentials.get_frozen_credentials()

        assert frozen.access_key == "ASIASECOND"
        assert frozen.token == "token-SECOND"
        calls = client.return_value.assume_role.call_args_list
        assert [call.kwargs["RoleArn"] for call in calls] == [OUR_ROLE_ARN, ROLE_ARN, ROLE_ARN] * 2
        ours, probe, customer = (call.kwargs for call in calls[3:])
        assert json.loads(ours["Policy"])["Statement"] == [
            {"Effect": "Allow", "Action": ["sts:AssumeRole"], "Resource": ROLE_ARN}
        ]
        assert probe["ExternalId"] != customer["ExternalId"] == f"posthog-{self.team.organization_id}"
        assert json.loads(customer["Policy"])["Statement"] == [
            {"Effect": "Allow", "Action": ["config:Describe*", "config:Get*"], "Resource": "*"}
        ]

    def test_unknown_selection_is_refused_even_with_keys(self) -> None:
        auth = Auth(selection="Role", aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="example-secret")

        with self.assertRaises(AwsAuthError):
            resolve_aws_credentials(auth, self.team.id, SESSION_ACTIONS)

    @parameterized.expand(["other_team", "batch_exports_role", "github", "deleted"])
    def test_connection_the_source_cannot_use_is_not_found(self, case: str) -> None:
        if case == "other_team":
            other_team = Team.objects.create(organization=Organization.objects.create(name="other"))
            integration_id = self._integration(other_team, aws_role_arn=ROLE_ARN).id
        elif case == "batch_exports_role":
            integration_id = self._integration(self.team, kind="aws-s3", aws_role_arn=ROLE_ARN).id
        elif case == "github":
            integration_id = self._integration(self.team, kind="github").id
        else:
            integration_id = 999999
        client = sts()

        with self.assertRaisesMessage(AwsAuthError, ROLE_NOT_FOUND_ERROR):
            self._resolve(client, integration_id)
        client.assert_not_called()

    @parameterized.expand(
        [
            ("customer_role_denied", OUR_ROLE_ARN, chain(sts_error("AccessDenied")), ROLE_ACCESS_DENIED_ERROR),
            (
                "random_external_id_accepted",
                OUR_ROLE_ARN,
                [session("OURS"), session("PROBE")],
                ROLE_EXTERNAL_ID_NOT_ENFORCED_ERROR,
            ),
            ("no_posthog_role", "", [], ROLE_UNAVAILABLE_ERROR),
        ]
    )
    def test_role_failures_raise_a_stable_message(
        self, _name: str, our_role_arn: str, answers: list[Any], message: str
    ) -> None:
        integration = self._integration(self.team, aws_role_arn=ROLE_ARN)

        with (
            override_settings(WAREHOUSE_SOURCES_AWS_ROLE_ARN=our_role_arn),
            self.assertRaisesMessage(AwsAuthError, message),
        ):
            self._resolve(sts(*answers), integration.id)

    @parameterized.expand(
        [
            ("throttled", chain(sts_error("Throttling"))),
            ("posthog_credentials_rejected", [sts_error("InvalidClientTokenId", "The security token is invalid.")]),
            ("posthog_role_denied", [sts_error("AccessDenied", f"not authorized on resource: {OUR_ROLE_ARN}")]),
            ("unreachable", [EndpointConnectionError(endpoint_url="https://sts.amazonaws.com")]),
        ]
    )
    def test_failure_the_user_cannot_fix_retries_without_the_aws_code(self, _name: str, answers: list[Any]) -> None:
        integration = self._integration(self.team, aws_role_arn=ROLE_ARN)

        with self.assertRaises(AwsAuthError) as raised:
            self._resolve(sts(*answers), integration.id)

        assert str(raised.exception) == ROLE_CREDENTIALS_RETRY_ERROR
        assert not error_message_matches(
            str(raised.exception),
            SourceRegistry.get_source(ExternalDataSourceType.AWSCONFIG).get_non_retryable_errors(),
        )

    @parameterized.expand(
        [
            ("throttled", [sts_error("Throttling")]),
            ("unreachable", [EndpointConnectionError(endpoint_url="https://sts.amazonaws.com")]),
            ("customer_role_denied", chain(sts_error("AccessDenied"))),
        ]
    )
    def test_failed_advisory_refresh_waits_before_calling_sts_again(self, _name: str, failure: list[Any]) -> None:
        integration = self._integration(self.team, aws_role_arn=ROLE_ARN)
        client = sts(*chain(session("FIRST", dt.timedelta(minutes=12))), *failure, *failure)

        with patch("boto3.client", client):
            credentials = resolve_aws_credentials(
                Auth(aws_integration_id=integration.id), self.team.id, SESSION_ACTIONS
            )
            first = credentials.get_frozen_credentials()
            with self.assertNoLogs("botocore.credentials", level="WARNING"):
                second = credentials.get_frozen_credentials()

        assert first.access_key == second.access_key == "ASIAFIRST"
        our_hops = [c for c in client.return_value.assume_role.call_args_list if c.kwargs["RoleArn"] == OUR_ROLE_ARN]
        assert len(our_hops) == 2


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


@parameterized.expand(
    [
        ("user_must_fix", AwsAuthError(MISSING_ROLE_ERROR), MISSING_ROLE_ERROR),
        ("temporary", AwsAuthError(ROLE_CREDENTIALS_RETRY_ERROR), None),
    ]
)
def test_endpoint_reasons_block_tables_only_for_errors_the_user_must_fix(
    _name: str, error: AwsAuthError, reason: str | None
) -> None:
    assert aws_auth_endpoint_reasons(error, ["a", "b"]) == {"a": reason, "b": reason}


def test_every_source_with_the_aws_auth_field_lifts_it_and_reads_only_with_its_own_kind_and_actions() -> None:
    problems = []
    for source_type, source in SourceRegistry.get_all_sources().items():
        if not any(field.name == AWS_AUTH_FIELD_NAME for field in source.get_source_config.fields):
            continue
        if AWS_AUTH_FIELD_NAME not in source.flat_stored_selects:
            problems.append(f"{source_type} does not set flat_stored_selects")
        if source.credential_kind == "aws-warehouse-sources":
            problems.append(f"{source_type} inherits the role connection's credential kind")
        actions = getattr(source, "aws_session_actions", ())
        if not actions:
            problems.append(f"{source_type} declares no aws_session_actions")
        for action in actions:
            service, _, name = action.partition(":")
            if not service or not name or name == "*":
                problems.append(f"{source_type} allows a whole service or every action: {action}")
            elif not name.startswith(READ_VERBS) and action != "kms:Decrypt":
                if action not in NON_READ_ACTIONS.get(source_type, set()):
                    problems.append(f"{source_type} allows an action that is not a read: {action}")
    assert problems == []
