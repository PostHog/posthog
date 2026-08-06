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
    build_params,
    error_for_response,
    get_rows,
    normalize_results,
    send_request,
    suppression_window,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.settings import (
    AWS_SES_ENDPOINTS,
    DEFAULT_PAGE_SIZE,
    SES_HOST_TEMPLATE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

LOGGER = structlog.get_logger()

ACCOUNT = AWS_SES_ENDPOINTS["account"]
CONFIGURATION_SETS = AWS_SES_ENDPOINTS["configuration_sets"]
EMAIL_IDENTITIES = AWS_SES_ENDPOINTS["email_identities"]
SUPPRESSED = AWS_SES_ENDPOINTS["suppressed_destinations"]


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


class TestNormalizeResults:
    def test_account_flattens_the_single_object_into_one_row(self) -> None:
        body = {
            "SendingEnabled": True,
            "EnforcementStatus": "HEALTHY",
            "SendQuota": {"Max24HourSend": 50000.0, "MaxSendRate": 14.0, "SentLast24Hours": 12.0},
            "SuppressionAttributes": {"SuppressedReasons": ["BOUNCE", "COMPLAINT"]},
        }

        rows = normalize_results(ACCOUNT, body)

        assert rows == [
            {
                "sending_enabled": True,
                "enforcement_status": "HEALTHY",
                "send_quota_max24_hour_send": 50000.0,
                "send_quota_max_send_rate": 14.0,
                "send_quota_sent_last24_hours": 12.0,
                "suppression_attributes_suppressed_reasons": ["BOUNCE", "COMPLAINT"],
            }
        ]

    def test_configuration_sets_wrap_bare_names_into_a_named_column(self) -> None:
        # ListConfigurationSets returns strings, not objects; a regression that flattened them
        # would emit unusable per-character rows.
        rows = normalize_results(CONFIGURATION_SETS, {"ConfigurationSets": ["marketing", "transactional"]})

        assert rows == [
            {"configuration_set_name": "marketing"},
            {"configuration_set_name": "transactional"},
        ]

    def test_email_identities_flatten_each_object(self) -> None:
        body = {
            "EmailIdentities": [
                {
                    "IdentityType": "DOMAIN",
                    "IdentityName": "example.com",
                    "SendingEnabled": True,
                    "VerificationStatus": "SUCCESS",
                }
            ]
        }

        rows = normalize_results(EMAIL_IDENTITIES, body)

        assert rows == [
            {
                "identity_type": "DOMAIN",
                "identity_name": "example.com",
                "sending_enabled": True,
                "verification_status": "SUCCESS",
            }
        ]

    def test_suppressed_destinations_coerce_the_epoch_cursor_to_a_datetime(self) -> None:
        # SESv2 serializes body timestamps as epoch seconds; without coercion the incremental
        # cursor would be a bare float and merge/watermark comparisons would break.
        body = {
            "SuppressedDestinationSummaries": [
                {"EmailAddress": "user@example.com", "Reason": "BOUNCE", "LastUpdateTime": 1614556800.0}
            ]
        }

        rows = normalize_results(SUPPRESSED, body)

        assert rows == [
            {
                "email_address": "user@example.com",
                "reason": "BOUNCE",
                "last_update_time": dt.datetime(2021, 3, 1, tzinfo=dt.UTC),
            }
        ]

    def test_a_missing_list_key_yields_no_rows(self) -> None:
        assert normalize_results(EMAIL_IDENTITIES, {}) == []


class TestSuppressionWindow:
    def test_first_sync_asks_for_everything_up_to_now(self) -> None:
        now = dt.datetime(2024, 3, 5, 10, 0, tzinfo=dt.UTC)

        start, end = suppression_window(
            should_use_incremental_field=False, db_incremental_field_last_value=None, now=now
        )

        assert start is None
        assert end == "2024-03-05T10:00:00Z"

    def test_end_date_never_reaches_past_now(self) -> None:
        # The AWS Cost Explorer bug (f46ea3d) was requesting a still-open period. SES filters on
        # LastUpdateTime, so the window must stop at the present instant, never beyond it.
        now = dt.datetime(2024, 3, 5, 10, 0, tzinfo=dt.UTC)

        _, end = suppression_window(True, dt.datetime(2024, 3, 1, tzinfo=dt.UTC), now)

        assert end == "2024-03-05T10:00:00Z"

    def test_incremental_rewinds_the_start_behind_the_watermark(self) -> None:
        # SES bumps LastUpdateTime on re-suppression, so the scan rewinds a couple of days to
        # re-read anything restated just after the previous sync.
        now = dt.datetime(2024, 3, 5, 10, 0, tzinfo=dt.UTC)
        watermark = dt.datetime(2024, 3, 4, 9, 0, tzinfo=dt.UTC)

        start, _ = suppression_window(True, watermark, now)

        assert start == "2024-03-02T09:00:00Z"


class TestBuildParams:
    def test_paginated_endpoints_request_a_page_size(self) -> None:
        params = build_params(EMAIL_IDENTITIES, next_token=None, start_date=None, end_date=None)

        assert params == {"PageSize": DEFAULT_PAGE_SIZE}

    def test_account_endpoint_sends_no_pagination_params(self) -> None:
        assert build_params(ACCOUNT, next_token=None, start_date=None, end_date=None) == {}

    def test_suppression_window_and_cursor_are_carried_as_query_params(self) -> None:
        params = build_params(
            SUPPRESSED, next_token="tok", start_date="2024-03-02T09:00:00Z", end_date="2024-03-05T10:00:00Z"
        )

        assert params == {
            "PageSize": DEFAULT_PAGE_SIZE,
            "StartDate": "2024-03-02T09:00:00Z",
            "EndDate": "2024-03-05T10:00:00Z",
            "NextToken": "tok",
        }


class TestSendRequest:
    def test_get_is_sigv4_signed_for_the_configured_region(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = make_response(200, {"SendingEnabled": True})
        credentials = aws_ses.Credentials("AKIAEXAMPLE", "secret")

        with freeze_time("2024-03-05T10:00:00Z"):
            body = send_request(session, credentials, "eu-west-1", ACCOUNT, {})

        assert body == {"SendingEnabled": True}
        url = session.get.call_args[0][0]
        assert url == f"https://{SES_HOST_TEMPLATE.format(region='eu-west-1')}/v2/email/account"
        headers = session.get.call_args[1]["headers"]
        assert headers["X-Amz-Date"] == "20240305T100000Z"
        assert headers["Authorization"].startswith(
            "AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/20240305/eu-west-1/ses/aws4_request"
        )

    def test_query_params_are_appended_to_the_signed_url(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = make_response(200, {"SuppressedDestinationSummaries": []})

        send_request(session, aws_ses.Credentials("k", "s"), "us-east-1", SUPPRESSED, {"PageSize": 1000})

        assert session.get.call_args[0][0].endswith("/v2/email/suppression/addresses?PageSize=1000")

    def test_temporary_credentials_carry_the_session_token(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = make_response(200, {})

        send_request(session, aws_ses.Credentials("k", "s", "session-token"), "us-east-1", ACCOUNT, {})

        assert session.get.call_args[1]["headers"]["X-Amz-Security-Token"] == "session-token"

    def test_an_error_status_raises(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = make_response(
            403, {"message": "denied"}, {"x-amzn-errortype": "AccessDeniedException"}
        )

        with pytest.raises(AwsSesError):
            send_request(session, aws_ses.Credentials("k", "s"), "us-east-1", ACCOUNT, {})


class TestErrorForResponse:
    @pytest.mark.parametrize("header_name", ["x-amzn-ErrorType", "x-amzn-errortype"])
    def test_the_error_type_header_names_the_failure(self, header_name: str) -> None:
        response = make_response(
            403, {"message": "nope"}, headers={header_name: "AccessDeniedException:http://internal/"}
        )

        assert str(error_for_response(response)) == "AWS SES request failed: AccessDeniedException - nope"

    def test_a_non_json_error_body_still_produces_a_usable_message(self) -> None:
        response = requests.Response()
        response.status_code = 503
        response._content = b"<html>gateway</html>"

        assert "HTTP 503" in str(error_for_response(response))


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "key,secret,region,expected",
        [
            ("", "secret", "us-east-1", "AWS access key ID and secret access key are required"),
            ("key", "", "us-east-1", "AWS access key ID and secret access key are required"),
            ("key", "secret", "", "An AWS region is required"),
        ],
    )
    def test_missing_inputs_short_circuit_without_a_request(
        self, key: str, secret: str, region: str, expected: str
    ) -> None:
        with mock.patch.object(aws_ses, "send_request") as send:
            assert validate_credentials(key, secret, None, region) == (False, expected)

        send.assert_not_called()

    def test_a_successful_probe_validates_via_get_account(self) -> None:
        with mock.patch.object(aws_ses, "send_request", return_value={"SendingEnabled": True}) as send:
            assert validate_credentials("key", "secret", None, "us-east-1") == (True, None)

        assert send.call_args[0][3] is ACCOUNT

    def test_an_api_error_is_surfaced_to_the_user(self) -> None:
        error = AwsSesError("AWS SES request failed: AccessDeniedException - denied")

        with mock.patch.object(aws_ses, "send_request", side_effect=error):
            assert validate_credentials("key", "secret", None, "us-east-1") == (False, str(error))


def run_rows(
    manager: FakeResumeManager,
    pages: list[dict[str, Any]],
    endpoint: str = "email_identities",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> tuple[list[dict[str, Any]], mock.MagicMock]:
    with (
        mock.patch.object(aws_ses, "make_session", return_value=mock.MagicMock(spec=requests.Session)),
        mock.patch.object(aws_ses, "send_request", side_effect=pages) as send,
    ):
        rows = [
            row
            for batch in get_rows(
                aws_access_key_id="key",
                aws_secret_access_key="secret",
                aws_session_token=None,
                region="us-east-1",
                endpoint=endpoint,
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
                logger=LOGGER,
            )
            for row in batch
        ]
    return rows, send


class TestGetRows:
    def test_pagination_follows_next_token_until_it_runs_out(self) -> None:
        manager = FakeResumeManager()
        pages = [
            {"EmailIdentities": [{"IdentityName": "a@example.com"}], "NextToken": "p2"},
            {"EmailIdentities": [{"IdentityName": "b@example.com"}]},
        ]

        rows, send = run_rows(manager, pages)

        assert [r["identity_name"] for r in rows] == ["a@example.com", "b@example.com"]
        assert send.call_count == 2
        # Second call must carry the cursor from the first page, or it re-reads page one forever.
        assert send.call_args_list[1][0][4]["NextToken"] == "p2"
        assert manager.cleared is True

    def test_state_is_saved_after_each_page_so_a_crash_re_yields_not_skips(self) -> None:
        manager = FakeResumeManager()
        pages = [
            {"EmailIdentities": [{"IdentityName": "a@example.com"}], "NextToken": "p2"},
            {"EmailIdentities": [{"IdentityName": "b@example.com"}]},
        ]

        run_rows(manager, pages)

        assert [s.next_token for s in manager.saved] == ["p2", None]

    def test_a_resumed_run_continues_from_the_saved_cursor(self) -> None:
        manager = FakeResumeManager(AwsSesResumeConfig(next_token="p2"))
        pages = [{"EmailIdentities": [{"IdentityName": "b@example.com"}]}]

        rows, send = run_rows(manager, pages)

        assert [r["identity_name"] for r in rows] == ["b@example.com"]
        assert send.call_args_list[0][0][4]["NextToken"] == "p2"

    def test_account_makes_a_single_unpaginated_call(self) -> None:
        manager = FakeResumeManager()

        rows, send = run_rows(manager, [{"SendingEnabled": True}], endpoint="account")

        assert send.call_count == 1
        assert "NextToken" not in send.call_args_list[0][0][4]
        assert rows == [{"sending_enabled": True}]

    def test_incremental_suppression_freezes_a_window_and_reuses_it_on_resume(self) -> None:
        watermark = dt.datetime(2024, 3, 4, 9, 0, tzinfo=dt.UTC)
        manager = FakeResumeManager()

        with freeze_time("2024-03-05T10:00:00Z"):
            _, send = run_rows(
                manager,
                [{"SuppressedDestinationSummaries": []}],
                endpoint="suppressed_destinations",
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )

        params = send.call_args_list[0][0][4]
        assert params["StartDate"] == "2024-03-02T09:00:00Z"
        assert params["EndDate"] == "2024-03-05T10:00:00Z"

        # A resumed attempt must reuse the frozen window rather than compute a fresh (later) one,
        # or the resumed NextToken would be paired with a different request.
        resumed = FakeResumeManager(
            AwsSesResumeConfig(next_token="p2", start_date="2024-03-02T09:00:00Z", end_date="2024-03-05T10:00:00Z")
        )
        with freeze_time("2024-03-06T10:00:00Z"):
            _, resumed_send = run_rows(
                resumed,
                [{"SuppressedDestinationSummaries": []}],
                endpoint="suppressed_destinations",
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )

        assert resumed_send.call_args_list[0][0][4]["EndDate"] == "2024-03-05T10:00:00Z"
