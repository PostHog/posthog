import json
import datetime as dt
from typing import Any, Optional

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses import aws_ses
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.aws_ses import (
    AwsSesError,
    AwsSesResumeConfig,
    Credentials,
    error_for_response,
    get_rows,
    normalize_row,
    probe_endpoint_permissions,
    resolve_start_date,
    send_request,
    validate_credentials,
    validate_region,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.settings import AWS_SES_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

LOGGER = structlog.get_logger()

EMAIL_IDENTITIES = AWS_SES_ENDPOINTS["email_identities"]

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
    @pytest.mark.parametrize("region", ["us-east-1", "eu-central-1", "ap-southeast-2", "us-gov-west-1"])
    def test_well_formed_regions_pass(self, region: str) -> None:
        assert validate_region(region) == region

    @pytest.mark.parametrize(
        "region",
        ["", "US-EAST-1", "us east 1", "email.evil.example/", "us-east-1/path", "us-east-1?x=1", "evil.example#"],
    )
    def test_anything_outside_the_region_alphabet_is_rejected_before_it_reaches_the_host(self, region: str) -> None:
        # The region is interpolated into the signed request's host.
        with pytest.raises(ValueError, match="Invalid AWS region"):
            validate_region(region)


class TestNormalizeRow:
    def test_account_response_flattens_into_prefixed_snake_case_columns(self) -> None:
        row = normalize_row(
            AWS_SES_ENDPOINTS["account"],
            {
                "SendingEnabled": True,
                "EnforcementStatus": "HEALTHY",
                "ProductionAccessEnabled": True,
                "SendQuota": {"Max24HourSend": 50000.0, "MaxSendRate": 14.0, "SentLast24Hours": 12.5},
                "SuppressionAttributes": {"SuppressedReasons": ["BOUNCE", "COMPLAINT"]},
            },
        )

        assert row == {
            "sending_enabled": True,
            "enforcement_status": "HEALTHY",
            "production_access_enabled": True,
            "send_quota_max24_hour_send": 50000.0,
            "send_quota_max_send_rate": 14.0,
            "send_quota_sent_last24_hours": 12.5,
            "suppression_attributes_suppressed_reasons": ["BOUNCE", "COMPLAINT"],
        }

    def test_identity_detail_keeps_policy_maps_whole_and_parses_epoch_timestamps(self) -> None:
        row = normalize_row(
            EMAIL_IDENTITIES,
            {
                "IdentityType": "DOMAIN",
                "DkimAttributes": {
                    "SigningEnabled": True,
                    "Status": "SUCCESS",
                    "Tokens": ["token-1", "token-2"],
                    "LastKeyGenerationTimestamp": JAN_2025,
                },
                "MailFromAttributes": {"MailFromDomain": "mail.example.com"},
                "Policies": {"MyPolicy": '{"Version":"2012-10-17"}'},
                "Tags": [{"Key": "env", "Value": "prod"}],
                "VerificationInfo": {
                    "LastCheckedTimestamp": JAN_2025,
                    "SOARecord": {"PrimaryNameServer": "ns1.example.com", "SerialNumber": 7},
                },
            },
        )

        assert row["identity_type"] == "DOMAIN"
        assert row["dkim_attributes_signing_enabled"] is True
        assert row["dkim_attributes_status"] == "SUCCESS"
        assert row["dkim_attributes_tokens"] == ["token-1", "token-2"]
        assert row["dkim_attributes_last_key_generation_timestamp"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
        assert row["mail_from_attributes_mail_from_domain"] == "mail.example.com"
        # A policy map has caller-defined keys; flattening it would mint one column per policy.
        assert row["policies"] == {"MyPolicy": '{"Version":"2012-10-17"}'}
        assert row["tags"] == [{"Key": "env", "Value": "prod"}]
        assert row["verification_info_last_checked_timestamp"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
        assert row["verification_info_soa_record_primary_name_server"] == "ns1.example.com"
        assert row["verification_info_soa_record_serial_number"] == 7


class TestSendRequest:
    def test_requests_are_sigv4_signed_with_the_regional_ses_scope(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = make_response(200, {})
        credentials = Credentials("AKIAEXAMPLE", "secret")

        with freeze_time("2026-08-07T10:00:00Z"):
            send_request(session, credentials, "eu-west-1", "/v2/email/account")

        assert session.get.call_args[0][0] == "https://email.eu-west-1.amazonaws.com/v2/email/account"
        headers = session.get.call_args[1]["headers"]
        assert headers["X-Amz-Date"] == "20260807T100000Z"
        assert headers["Authorization"].startswith(
            "AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/20260807/eu-west-1/ses/aws4_request"
        )

    def test_query_params_are_sorted_and_rfc3986_encoded_to_match_the_signed_string(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = make_response(200, {})

        send_request(
            session,
            Credentials("key", "secret"),
            "us-east-1",
            "/v2/email/suppression/addresses",
            {"StartDate": "2026-08-01T00:00:00Z", "PageSize": 1000},
        )

        assert session.get.call_args[0][0].endswith(
            "/v2/email/suppression/addresses?PageSize=1000&StartDate=2026-08-01T00%3A00%3A00Z"
        )

    def test_temporary_credentials_carry_the_session_token(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = make_response(200, {})

        send_request(session, Credentials("key", "secret", "session-token"), "us-east-1", "/v2/email/account")

        assert session.get.call_args[1]["headers"]["X-Amz-Security-Token"] == "session-token"


class TestErrorClassification:
    def test_the_error_type_header_wins_over_the_body(self) -> None:
        response = make_response(
            400,
            {"message": "denied"},
            headers={"x-amzn-ErrorType": "AccessDeniedException:http://internal.amazon.example/coral/"},
        )

        assert str(error_for_response(response)) == "Amazon SES request failed: AccessDeniedException - denied"

    def test_the_namespaced_body_type_is_stripped_to_the_bare_code(self) -> None:
        response = make_response(400, {"__type": "com.amazonaws.ses#BadRequestException", "message": "bad"})

        assert str(error_for_response(response)) == "Amazon SES request failed: BadRequestException - bad"

    def test_a_non_json_error_body_still_produces_a_usable_message(self) -> None:
        response = requests.Response()
        response.status_code = 503
        response._content = b"<html>gateway</html>"

        assert "HTTP 503" in str(error_for_response(response))


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
        assert send.call_args[0][3] == "/v2/email/account"

    def test_pagination_follows_next_token_until_aws_stops_returning_one(self) -> None:
        batches, send, _ = self._run(
            [
                suppression_page(["a@example.com"], next_token="page-2"),
                suppression_page(["b@example.com"]),
            ]
        )

        assert [row["email_address"] for batch in batches for row in batch] == ["a@example.com", "b@example.com"]
        assert batches[0][0]["last_update_time"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
        assert "NextToken" not in send.call_args_list[0][0][4]
        assert send.call_args_list[1][0][4]["NextToken"] == "page-2"

    def test_state_is_saved_after_each_page_and_cleared_once_the_walk_completes(self) -> None:
        _, _, manager = self._run(
            [
                suppression_page(["a@example.com"], next_token="page-2"),
                suppression_page(["b@example.com"]),
            ]
        )

        assert manager.saved == [AwsSesResumeConfig(next_token="page-2"), AwsSesResumeConfig(next_token=None)]
        assert manager.cleared is True

    def test_a_saved_token_resumes_the_walk_at_the_saved_page(self) -> None:
        _, send, _ = self._run(
            [suppression_page(["z@example.com"])],
            manager=FakeResumeManager(AwsSesResumeConfig(next_token="page-7")),
        )

        assert send.call_count == 1
        assert send.call_args[0][4]["NextToken"] == "page-7"

    def test_an_expired_saved_token_restarts_the_walk_instead_of_failing_the_job(self) -> None:
        batches, send, manager = self._run(
            [
                AwsSesError("Amazon SES request failed: InvalidNextTokenException - expired"),
                suppression_page(["a@example.com"]),
            ],
            manager=FakeResumeManager(AwsSesResumeConfig(next_token="stale")),
        )

        assert [row["email_address"] for batch in batches for row in batch] == ["a@example.com"]
        assert send.call_args_list[0][0][4].get("NextToken") == "stale"
        assert "NextToken" not in send.call_args_list[1][0][4]
        assert manager.cleared is True

    def test_an_invalid_token_from_aws_itself_is_not_swallowed(self) -> None:
        # Restarting is only safe for a token we saved; a fresh token AWS just returned failing
        # means something else is wrong.
        with pytest.raises(AwsSesError, match="InvalidNextTokenException"):
            self._run(
                [
                    AwsSesError("Amazon SES request failed: InvalidNextTokenException - expired"),
                    AwsSesError("Amazon SES request failed: InvalidNextTokenException - expired"),
                ],
                manager=FakeResumeManager(AwsSesResumeConfig(next_token="stale")),
            )

    def test_an_incremental_run_asks_aws_only_for_updates_since_the_watermark(self) -> None:
        _, send, _ = self._run(
            [suppression_page([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=dt.datetime(2026, 8, 7, 12, 0, tzinfo=dt.UTC),
        )

        assert send.call_args[0][4]["StartDate"] == "2026-08-06T12:00:00Z"

    def test_a_full_refresh_walks_the_list_unbounded(self) -> None:
        _, send, _ = self._run([suppression_page([])])

        assert "StartDate" not in send.call_args[0][4]

    def test_configuration_sets_fan_out_from_bare_names_to_full_rows(self) -> None:
        batches, send, _ = self._run(
            [
                {"ConfigurationSets": ["transactional"], "NextToken": "page-2"},
                {
                    "ConfigurationSetName": "transactional",
                    "SendingOptions": {"SendingEnabled": True},
                    "ReputationOptions": {"LastFreshStart": JAN_2025},
                },
                {"ConfigurationSets": ["marketing"]},
                {"TrackingOptions": {"CustomRedirectDomain": "links.example.com"}},
            ],
            endpoint="configuration_sets",
        )

        assert send.call_args_list[1][0][3] == "/v2/email/configuration-sets/transactional"
        first, second = batches[0][0], batches[1][0]
        assert first["configuration_set_name"] == "transactional"
        assert first["sending_options_sending_enabled"] is True
        assert first["reputation_options_last_fresh_start"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
        assert second["configuration_set_name"] == "marketing"
        assert second["tracking_options_custom_redirect_domain"] == "links.example.com"

    def test_identity_rows_merge_the_list_summary_with_the_detail_and_keep_the_name(self) -> None:
        # GetEmailIdentity does not echo the identity name back, so the row must carry it from
        # the list response or the primary key column would be empty.
        batches, send, _ = self._run(
            [
                {
                    "EmailIdentities": [
                        {
                            "IdentityName": "user@example.com",
                            "IdentityType": "EMAIL_ADDRESS",
                            "SendingEnabled": True,
                            "VerificationStatus": "SUCCESS",
                        }
                    ]
                },
                {"IdentityType": "EMAIL_ADDRESS", "VerifiedForSendingStatus": True},
            ],
            endpoint="email_identities",
        )

        assert send.call_args_list[1][0][3] == "/v2/email/identities/user%40example.com"
        row = batches[0][0]
        assert row["identity_name"] == "user@example.com"
        assert row["sending_enabled"] is True
        assert row["verification_status"] == "SUCCESS"
        assert row["verified_for_sending_status"] is True

    def test_an_item_deleted_between_list_and_detail_is_skipped_not_fatal(self) -> None:
        batches, _, _ = self._run(
            [
                {"EmailIdentities": [{"IdentityName": "gone.example.com"}, {"IdentityName": "kept.example.com"}]},
                AwsSesError("Amazon SES request failed: NotFoundException - not found"),
                {"IdentityType": "DOMAIN"},
            ],
            endpoint="email_identities",
        )

        assert [row["identity_name"] for batch in batches for row in batch] == ["kept.example.com"]

    def test_an_empty_page_yields_no_batch_but_still_completes_the_walk(self) -> None:
        batches, _, manager = self._run([suppression_page([])])

        assert batches == []
        assert manager.cleared is True


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

        assert send.call_args[0][3] == "/v2/email/account"

    def test_a_genuine_key_missing_the_account_permission_still_validates_at_create(self) -> None:
        # Scope for each table is reported per endpoint in the schema picker instead.
        error = AwsSesError("Amazon SES request failed: AccessDeniedException - not authorized")

        with mock.patch.object(aws_ses, "send_request", side_effect=error):
            assert validate_credentials("key", "secret", None, "us-east-1") == (True, None)

    def test_a_rejected_key_is_surfaced_to_the_user(self) -> None:
        error = AwsSesError("Amazon SES request failed: UnrecognizedClientException - invalid token")

        with mock.patch.object(aws_ses, "send_request", side_effect=error):
            assert validate_credentials("key", "secret", None, "us-east-1") == (False, str(error))

    def test_a_transport_failure_does_not_leak_internals(self) -> None:
        with mock.patch.object(aws_ses, "send_request", side_effect=requests.ConnectionError("boom")):
            assert validate_credentials("key", "secret", None, "us-east-1") == (
                False,
                "Could not reach the Amazon SES API. Check the AWS region and try again.",
            )

    def test_validating_a_schema_probes_that_endpoint_and_names_the_missing_permission(self) -> None:
        error = AwsSesError(
            "Amazon SES request failed: AccessDeniedException - User: arn:aws:iam::123456789012:user/etl "
            "is not authorized to perform: ses:ListSuppressedDestinations on resource: arn:aws:ses:us-east-1:123456789012:suppression-list"
        )

        with mock.patch.object(aws_ses, "send_request", side_effect=error):
            assert validate_credentials("key", "secret", None, "us-east-1", schema_name="suppressed_destinations") == (
                False,
                "Missing IAM permission ses:ListSuppressedDestinations",
            )

    def test_validating_a_schema_passes_when_the_endpoint_is_reachable(self) -> None:
        with mock.patch.object(aws_ses, "send_request", return_value=suppression_page([])):
            assert validate_credentials("key", "secret", None, "us-east-1", schema_name="suppressed_destinations") == (
                True,
                None,
            )


class TestEndpointPermissions:
    def test_only_the_denied_endpoint_is_reported_unreachable(self) -> None:
        def respond(session: Any, credentials: Any, region: str, path: str, params: Any = None) -> dict[str, Any]:
            if path == "/v2/email/account":
                raise AwsSesError(
                    "Amazon SES request failed: AccessDeniedException - not authorized to perform: ses:GetAccount"
                )
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
                "Amazon SES request failed: AccessDeniedException - not authorized to perform: ses:GetEmailIdentity"
            ),
        ]

        with mock.patch.object(aws_ses, "send_request", side_effect=responses):
            reasons = probe_endpoint_permissions("key", "secret", None, "us-east-1", ["email_identities"])

        assert reasons == {"email_identities": "Missing IAM permission ses:GetEmailIdentity"}

    def test_transient_failures_do_not_hide_tables_from_the_schema_picker(self) -> None:
        with mock.patch.object(
            aws_ses, "send_request", side_effect=AwsSesError("Amazon SES request failed: HTTP 503 - gateway")
        ):
            reasons = probe_endpoint_permissions("key", "secret", None, "us-east-1", ["suppressed_destinations"])

        assert reasons == {"suppressed_destinations": None}
