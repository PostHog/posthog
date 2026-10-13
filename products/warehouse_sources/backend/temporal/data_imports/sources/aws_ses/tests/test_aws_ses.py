import json
import datetime as dt
from typing import Any, Optional

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses import aws_ses
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.aws_ses import (
    AwsSesError,
    AwsSesResumeConfig,
    error_for_response,
    get_rows,
    probe_endpoint_permissions,
    resolve_start_date,
    validate_credentials,
    validate_region,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

LOGGER = structlog.get_logger()


JAN_2025 = 1735689600.0  # 2025-01-01T00:00:00Z


class FakeResumeManager(ResumableSourceManager[AwsSesResumeConfig]):
    def __init__(self, state: Optional[AwsSesResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[AwsSesResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[AwsSesResumeConfig]:
        return self.state

    def save_state(self, data: AwsSesResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


def make_response(
    status_code: int, payload: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None
) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.headers.update(headers or {})
    response._content = json.dumps(payload if payload is not None else {}).encode()
    return response


def suppression_page(emails: list[str], next_token: Optional[str] = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "SuppressedDestinationSummaries": [
            {"EmailAddress": email, "Reason": "BOUNCE", "LastUpdateTime": JAN_2025} for email in emails
        ]
    }
    if next_token is not None:
        body["NextToken"] = next_token
    return body


class TestRegionValidation:
    @pytest.mark.parametrize(
        "region",
        ["", "US-EAST-1", "us east 1", "email.evil.example/", "us-east-1/path", "us-east-1?x=1", "evil.example#"],
    )
    def test_anything_outside_the_region_alphabet_is_rejected_before_it_reaches_the_host(self, region: str) -> None:
        # The region is interpolated into the signed request's host.
        with pytest.raises(ValueError, match="Invalid AWS region"):
            validate_region(region)


class TestErrorClassification:
    def test_an_email_identity_in_the_path_is_masked(self) -> None:
        response = make_response(400, {"message": "bad"})

        message = str(error_for_response(response, "email_identities", "/v2/email/identities/user%40example.com"))

        assert message.endswith("(table email_identities, GET /v2/email/identities/{email})")
        assert "example.com" not in message

    def test_a_non_json_error_body_still_produces_a_usable_message(self) -> None:
        response = requests.Response()
        response.status_code = 503
        response._content = b"<html>gateway</html>"

        assert "HTTP 503" in str(error_for_response(response, "account", "/v2/email/account"))


class TestResolveStartDate:
    WATERMARK = dt.datetime(2026, 8, 7, 12, 0, tzinfo=dt.UTC)

    @pytest.mark.parametrize(
        "watermark",
        ["2026-08-07T12:00:00Z", dt.datetime(2026, 8, 7, 12, 0, tzinfo=dt.UTC)],
    )
    def test_incremental_rewinds_a_day_behind_the_watermark(self, watermark: Any) -> None:
        assert resolve_start_date(True, watermark) == dt.datetime(2026, 8, 6, 12, 0, tzinfo=dt.UTC)

    @pytest.mark.parametrize(
        "should_use_incremental_field,watermark",
        [(False, dt.datetime(2026, 8, 7, tzinfo=dt.UTC)), (True, None), (True, "not-a-date")],
    )
    def test_no_usable_watermark_means_a_full_unbounded_walk(
        self, should_use_incremental_field: bool, watermark: Any
    ) -> None:
        assert resolve_start_date(should_use_incremental_field, watermark) is None


class TestGetRows:
    def _run(
        self,
        responses: list[Any],
        manager: Optional[FakeResumeManager] = None,
        endpoint: str = "suppressed_destinations",
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[list[dict[str, Any]]], mock.MagicMock, FakeResumeManager]:
        manager = manager if manager is not None else FakeResumeManager()
        with mock.patch.object(aws_ses, "send_request", side_effect=responses) as send:
            batches = list(
                get_rows(
                    aws_access_key_id="key",
                    aws_secret_access_key="secret",
                    aws_session_token=None,
                    aws_region="us-east-1",
                    endpoint=endpoint,
                    resumable_source_manager=manager,
                    should_use_incremental_field=should_use_incremental_field,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                    logger=LOGGER,
                )
            )
        return batches, send, manager

    def test_the_account_endpoint_yields_its_single_snapshot_row(self) -> None:
        batches, send, _ = self._run([{"SendingEnabled": True, "EnforcementStatus": "HEALTHY"}], endpoint="account")

        assert batches == [[{"sending_enabled": True, "enforcement_status": "HEALTHY"}]]
        assert send.call_count == 1
        assert send.call_args[0][4] == "/v2/email/account"

    def test_an_expired_saved_token_restarts_the_walk_instead_of_failing_the_job(self) -> None:
        batches, send, manager = self._run(
            [
                AwsSesError("InvalidNextTokenException", "expired", "suppressed_destinations", "/path"),
                suppression_page(["a@example.com"]),
            ],
            manager=FakeResumeManager(AwsSesResumeConfig(next_token="stale")),
        )

        assert [row["email_address"] for batch in batches for row in batch] == ["a@example.com"]
        assert send.call_args_list[0][0][5].get("NextToken") == "stale"
        assert "NextToken" not in send.call_args_list[1][0][5]
        assert manager.cleared is True

    def test_an_invalid_token_from_aws_itself_is_not_swallowed(self) -> None:
        # Restarting is only safe for a token we saved; a fresh token AWS just returned failing
        # means something else is wrong.
        with pytest.raises(AwsSesError, match="InvalidNextTokenException"):
            self._run(
                [
                    AwsSesError("InvalidNextTokenException", "expired", "suppressed_destinations", "/path"),
                    AwsSesError("InvalidNextTokenException", "expired", "suppressed_destinations", "/path"),
                ],
                manager=FakeResumeManager(AwsSesResumeConfig(next_token="stale")),
            )

    def test_a_saved_token_rejected_as_a_bad_request_restarts_the_walk(self) -> None:
        # Only ListSuppressedDestinations models a rejected token as InvalidNextTokenException.
        # Every other list operation answers one with BadRequestException, which is otherwise
        # classified as permanent and would disable a healthy table.
        batches, send, manager = self._run(
            [
                AwsSesError("BadRequestException", "invalid", "multi_region_endpoints", "/path"),
                {"MultiRegionEndpoints": [{"EndpointId": "e-1"}]},
            ],
            manager=FakeResumeManager(AwsSesResumeConfig(next_token="stale")),
            endpoint="multi_region_endpoints",
        )

        assert [row["endpoint_id"] for batch in batches for row in batch] == ["e-1"]
        assert send.call_args_list[0][0][5].get("NextToken") == "stale"
        assert "NextToken" not in send.call_args_list[1][0][5]
        assert manager.cleared is True

    def test_a_bad_request_that_outlives_the_restart_still_fails_the_job(self) -> None:
        # The region genuinely cannot serve the table: page 1 fails the same way, and the error
        # has to reach the non-retryable classification that disables the schema.
        with pytest.raises(AwsSesError, match="BadRequestException"):
            self._run(
                [
                    AwsSesError("BadRequestException", "invalid", "multi_region_endpoints", "/path"),
                    AwsSesError("BadRequestException", "invalid", "multi_region_endpoints", "/path"),
                ],
                manager=FakeResumeManager(AwsSesResumeConfig(next_token="stale")),
                endpoint="multi_region_endpoints",
            )

    def test_a_bad_request_with_no_saved_token_fails_without_a_retry(self) -> None:
        with pytest.raises(AwsSesError, match="BadRequestException"):
            self._run(
                [AwsSesError("BadRequestException", "invalid", "multi_region_endpoints", "/path")],
                endpoint="multi_region_endpoints",
            )

    def test_an_incremental_run_asks_aws_only_for_updates_since_the_watermark(self) -> None:
        _, send, _ = self._run(
            [suppression_page([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=dt.datetime(2026, 8, 7, 12, 0, tzinfo=dt.UTC),
        )

        assert send.call_args[0][5]["StartDate"] == "2026-08-06T12:00:00Z"

    def test_an_item_deleted_between_list_and_detail_is_skipped_not_fatal(self) -> None:
        batches, _, _ = self._run(
            [
                {"EmailIdentities": [{"IdentityName": "gone.example.com"}, {"IdentityName": "kept.example.com"}]},
                AwsSesError("NotFoundException", "not found", "email_identities", "/path"),
                {"IdentityType": "DOMAIN"},
            ],
            endpoint="email_identities",
        )

        assert [row["identity_name"] for batch in batches for row in batch] == ["kept.example.com"]

    @pytest.mark.parametrize("pool_name", ["ses-shared-pool", "ses-default-dedicated-pool"])
    def test_an_item_aws_refuses_to_describe_is_reported_from_the_list_response_alone(self, pool_name: str) -> None:
        batches, _, _ = self._run(
            [
                {"DedicatedIpPools": [pool_name, "marketing-pool"]},
                AwsSesError("BadRequestException", "shared or default pool", "dedicated_ip_pools", "/path"),
                {"DedicatedIpPool": {"PoolName": "marketing-pool", "ScalingMode": "MANAGED"}},
            ],
            endpoint="dedicated_ip_pools",
        )

        assert batches == [
            [
                {"pool_name": pool_name},
                {
                    "pool_name": "marketing-pool",
                    "dedicated_ip_pool_pool_name": "marketing-pool",
                    "dedicated_ip_pool_scaling_mode": "MANAGED",
                },
            ]
        ]

    @pytest.mark.parametrize(
        "endpoint,page,code",
        [
            ("dedicated_ip_pools", {"DedicatedIpPools": ["marketing-pool"]}, "TooManyRequestsException"),
            ("dedicated_ip_pools", {"DedicatedIpPools": ["marketing-pool"]}, "BadRequestException"),
            ("dedicated_ip_pools", {"DedicatedIpPools": ["ses-shared-pool-custom"]}, "BadRequestException"),
            ("dedicated_ip_pools", {"DedicatedIpPools": ["ses-shared-pool"]}, "AccessDeniedException"),
            ("dedicated_ip_pools", {"DedicatedIpPools": ["ses-default-dedicated-pool"]}, "TooManyRequestsException"),
            ("dedicated_ip_pools", {"DedicatedIpPools": ["ses-shared-pool"]}, "HTTP 503"),
            ("configuration_sets", {"ConfigurationSets": ["ses-shared-pool"]}, "BadRequestException"),
            ("contact_lists", {"ContactLists": [{"ContactListName": "ses-shared-pool"}]}, "BadRequestException"),
            (
                "custom_verification_email_templates",
                {"CustomVerificationEmailTemplates": [{"TemplateName": "ses-shared-pool"}]},
                "BadRequestException",
            ),
            ("email_identities", {"EmailIdentities": [{"IdentityName": "example.com"}]}, "BadRequestException"),
            ("email_templates", {"TemplatesMetadata": [{"TemplateName": "ses-shared-pool"}]}, "BadRequestException"),
        ],
    )
    def test_a_detail_failure_the_table_cannot_absorb_still_fails_the_job(
        self, endpoint: str, page: dict[str, Any], code: str
    ) -> None:
        with pytest.raises(AwsSesError, match=code):
            self._run([page, AwsSesError(code, "rejected", endpoint, "/path")], endpoint=endpoint)


class TestValidateCredentials:
    def test_missing_credentials_short_circuit_without_a_request(self) -> None:
        with mock.patch.object(aws_ses, "send_request") as send:
            assert validate_credentials("", "secret", None, "us-east-1") == (
                False,
                "AWS access key ID and secret access key are required",
            )

        send.assert_not_called()

    def test_a_malformed_region_short_circuits_without_a_request(self) -> None:
        with mock.patch.object(aws_ses, "send_request") as send:
            assert validate_credentials("key", "secret", None, "not a region") == (
                False,
                "'not a region' isn't a valid AWS region. Use a region code like us-east-1.",
            )

        send.assert_not_called()

    def test_a_successful_account_probe_validates(self) -> None:
        with mock.patch.object(aws_ses, "send_request", return_value={"SendingEnabled": True}) as send:
            assert validate_credentials("key", "secret", None, "us-east-1") == (True, None)

        assert send.call_args[0][4] == "/v2/email/account"

    def test_a_genuine_key_missing_the_account_permission_still_validates_at_create(self) -> None:
        # Scope for each table is reported per endpoint in the schema picker instead.
        error = AwsSesError("AccessDeniedException", "not authorized", "account", "/v2/email/account")

        with mock.patch.object(aws_ses, "send_request", side_effect=error):
            assert validate_credentials("key", "secret", None, "us-east-1") == (True, None)

    def test_a_rejected_key_is_surfaced_to_the_user(self) -> None:
        error = AwsSesError("UnrecognizedClientException", "invalid token", "account", "/v2/email/account")

        with mock.patch.object(aws_ses, "send_request", side_effect=error):
            assert validate_credentials("key", "secret", None, "us-east-1") == (False, str(error))

    def test_a_transport_failure_does_not_leak_internals(self) -> None:
        with mock.patch.object(aws_ses, "send_request", side_effect=requests.ConnectionError("boom")):
            assert validate_credentials("key", "secret", None, "us-east-1") == (
                False,
                "Could not reach the Amazon SES API. Check the AWS region and try again.",
            )


class TestEndpointPermissions:
    def test_only_the_denied_endpoint_is_reported_unreachable(self) -> None:
        def respond(
            session: Any, credentials: Any, region: str, endpoint: str, path: str, params: Any = None
        ) -> dict[str, Any]:
            if path == "/v2/email/account":
                raise AwsSesError("AccessDeniedException", "not authorized to perform: ses:GetAccount", endpoint, path)
            return {}

        with mock.patch.object(aws_ses, "send_request", side_effect=respond):
            reasons = probe_endpoint_permissions(
                "key", "secret", None, "us-east-1", ["account", "suppressed_destinations"]
            )

        assert reasons == {
            "account": "Missing IAM permission ses:GetAccount",
            "suppressed_destinations": None,
        }

    def test_a_denied_detail_call_marks_the_fan_out_endpoint_unreachable(self) -> None:
        # Probing only the list would hide a missing Get* permission until the sync fails.
        responses = [
            {"EmailIdentities": [{"IdentityName": "example.com"}]},
            AwsSesError(
                "AccessDeniedException",
                "not authorized to perform: ses:GetEmailIdentity",
                "email_identities",
                "/v2/email/identities/example.com",
            ),
        ]

        with mock.patch.object(aws_ses, "send_request", side_effect=responses):
            reasons = probe_endpoint_permissions("key", "secret", None, "us-east-1", ["email_identities"])

        assert reasons == {"email_identities": "Missing IAM permission ses:GetEmailIdentity"}

    def test_transient_failures_do_not_hide_tables_from_the_schema_picker(self) -> None:
        with mock.patch.object(
            aws_ses,
            "send_request",
            side_effect=AwsSesError(
                "HTTP 503", "gateway", "suppressed_destinations", "/v2/email/suppression/addresses"
            ),
        ):
            reasons = probe_endpoint_permissions("key", "secret", None, "us-east-1", ["suppressed_destinations"])

        assert reasons == {"suppressed_destinations": None}

    def test_a_table_the_region_cannot_serve_is_reported_instead_of_staying_selectable(self) -> None:
        # SESv2 answers an operation the region does not support with a bodyless 400.
        with mock.patch.object(
            aws_ses,
            "send_request",
            side_effect=AwsSesError(
                "BadRequestException", "no reason", "multi_region_endpoints", "/v2/email/multi-region-endpoints"
            ),
        ):
            reasons = probe_endpoint_permissions("key", "secret", None, "us-east-1", ["multi_region_endpoints"])

        assert reasons == {"multi_region_endpoints": aws_ses._BAD_REQUEST_EXPLANATION}

    @pytest.mark.parametrize(
        "pool_name,code,status_code,expected_reason",
        [
            ("ses-shared-pool", "BadRequestException", 400, None),
            ("ses-default-dedicated-pool", "BadRequestException", 400, None),
            ("marketing-pool", "BadRequestException", 400, aws_ses._BAD_REQUEST_EXPLANATION),
            ("ses-shared-pool-custom", "BadRequestException", 400, aws_ses._BAD_REQUEST_EXPLANATION),
            (
                "ses-shared-pool",
                "AccessDeniedException",
                403,
                "The connected IAM user or role is not allowed to read this table",
            ),
        ],
    )
    def test_pool_discovery_and_validation_only_allow_known_detail_rejections(
        self, requests_mock: Any, pool_name: str, code: str, status_code: int, expected_reason: Optional[str]
    ) -> None:
        pool_url = "https://email.us-east-1.amazonaws.com/v2/email/dedicated-ip-pools"
        requests_mock.get(pool_url, json={"DedicatedIpPools": [pool_name]})
        requests_mock.get(
            f"{pool_url}/{pool_name}", status_code=status_code, headers={"x-amzn-ErrorType": code}, json={}
        )

        assert probe_endpoint_permissions("key", "secret", None, "us-east-1", ["dedicated_ip_pools"]) == {
            "dedicated_ip_pools": expected_reason
        }
        assert validate_credentials("key", "secret", None, "us-east-1", schema_name="dedicated_ip_pools") == (
            expected_reason is None,
            expected_reason,
        )

    def test_a_rejected_pool_list_still_blocks_discovery_and_validation(self, requests_mock: Any) -> None:
        requests_mock.get(
            "https://email.us-east-1.amazonaws.com/v2/email/dedicated-ip-pools",
            status_code=400,
            headers={"x-amzn-ErrorType": "BadRequestException"},
            json={},
        )

        assert probe_endpoint_permissions("key", "secret", None, "us-east-1", ["dedicated_ip_pools"]) == {
            "dedicated_ip_pools": aws_ses._BAD_REQUEST_EXPLANATION
        }
        assert validate_credentials("key", "secret", None, "us-east-1", schema_name="dedicated_ip_pools") == (
            False,
            aws_ses._BAD_REQUEST_EXPLANATION,
        )
