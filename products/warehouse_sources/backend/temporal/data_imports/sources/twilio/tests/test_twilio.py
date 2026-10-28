from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twilio import (
    TwilioAuthMethodConfig,
    TwilioSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.settings import TWILIO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.source import TwilioSource
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.twilio import (
    CREDENTIAL_PROBE_ENDPOINTS,
    TWILIO_INVALID_CREDENTIALS_MESSAGE,
    TWILIO_MAIN_KEY_REQUIRED_MESSAGE,
    TWILIO_MAIN_KEY_REQUIRED_REASON,
    TWILIO_UNREACHABLE_MESSAGE,
    TwilioResumeConfig,
    _build_initial_params,
    _format_filter_date,
    _unexpected_status_message,
    validate_credentials,
)

ACCOUNT_SID = "AC00000000000000000000000000000000"
# A Standard API key, the credential the source's caption recommends.
API_KEY_AUTH = ("SK00000000000000000000000000000000", "secret")


def _response(body: dict[str, Any], status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


def _status(status_code: int) -> Script:
    return always(ScriptedResponse(status=status_code, json={}))


def _run(endpoint: str, script: Script, resume_state: TwilioResumeConfig | None = None, **kwargs: Any) -> DriveResult:
    config = TwilioSourceConfig(
        account_sid=ACCOUNT_SID,
        auth_method=TwilioAuthMethodConfig(selection="auth_token", auth_token="token"),
    )
    return SourceDriver(TwilioSource(), config).run(endpoint, script, resume_state=resume_state, **kwargs)


class TestFormatFilterDate:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04"),
            (datetime(2026, 1, 15, 10, 30, 45), "2026-01-15"),
            (date(2026, 3, 4), "2026-03-04"),
            ("2026-03-04T02:58:14Z", "2026-03-04"),
            ("Fri, 24 May 2019 17:44:46 +0000", "2019-05-24"),
            (1583290694, "2020-03-04"),  # epoch seconds
        ],
    )
    def test_format_filter_date(self, value, expected):
        assert _format_filter_date(value) == expected

    @pytest.mark.parametrize("value", ["not-a-date", "", None])
    def test_format_filter_date_raises_on_unparseable(self, value):
        # Better to fail loudly than emit a malformed filter Twilio rejects with error 20001.
        with pytest.raises(ValueError):
            _format_filter_date(value)


class TestBuildInitialParams:
    def test_incremental_defaults_to_single_filter_field(self):
        # `date_sent` is the only filter for messages, so a None selection still resolves to it.
        params = _build_initial_params(
            TWILIO_ENDPOINTS["messages"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field=None,
        )
        assert params["DateSent>"] == "2026-03-04"

    def test_verify_attempts_uses_datecreatedafter_with_iso_datetime(self):
        # Verify names the filter param outright (no `>` operator) and wants an ISO 8601 GMT datetime,
        # anchored to the start of the watermark's day so the boundary day is re-fetched and deduped.
        params = _build_initial_params(
            TWILIO_ENDPOINTS["verification_attempts"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 15, 0, tzinfo=UTC),
            incremental_field="date_created",
        )
        assert params["DateCreatedAfter"] == "2026-03-04T00:00:00Z"
        assert not any(key.endswith(">") for key in params)

    def test_full_refresh_endpoint_never_filters(self):
        # `transcriptions` exposes no server-side filter even if incremental is requested.
        params = _build_initial_params(
            TWILIO_ENDPOINTS["transcriptions"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="date_created",
        )
        assert params == {"PageSize": 1000}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, schema_name, expected_valid",
        [
            (200, None, True),
            (200, "messages", True),
            (401, None, False),
            (401, "messages", False),
            # Twilio denies by 401, so a 403 carries no extra meaning and cannot be accepted either.
            (403, None, False),
            (403, "messages", False),
            (404, None, False),
            (500, None, False),
        ],
    )
    def test_status_mapping(self, status_code, schema_name, expected_valid):
        with scripted_network(_status(status_code)):
            is_valid, _msg = validate_credentials((ACCOUNT_SID, "token"), ACCOUNT_SID, schema_name)
        assert is_valid is expected_valid

    def test_standard_api_key_denied_the_account_resource_is_still_accepted(self):
        # Twilio 401s the Accounts resource for Standard and Restricted API keys, so probing it at
        # source-create time rejected the credential the caption recommends.
        def _get(request: RecordedRequest) -> ScriptedResponse:
            status = 401 if request.path.endswith(f"Accounts/{ACCOUNT_SID}.json") else 200
            return ScriptedResponse(status=status, json={})

        with scripted_network(_get) as network:
            is_valid, msg = validate_credentials(API_KEY_AUTH, ACCOUNT_SID)

        assert (is_valid, msg) == (True, None)
        assert not any(request.path.endswith(f"Accounts/{ACCOUNT_SID}.json") for request in network.requests_log)

    def test_create_probe_rejects_when_every_candidate_is_denied(self):
        with scripted_network(_status(401)) as network:
            is_valid, msg = validate_credentials(API_KEY_AUTH, ACCOUNT_SID)

        assert (is_valid, msg) == (False, TWILIO_INVALID_CREDENTIALS_MESSAGE)
        assert len(network.requests_log) == len(CREDENTIAL_PROBE_ENDPOINTS)

    @pytest.mark.parametrize(
        "schema_name, expected_message",
        [
            ("keys", TWILIO_MAIN_KEY_REQUIRED_MESSAGE),
            ("accounts", TWILIO_MAIN_KEY_REQUIRED_MESSAGE),
            (
                "messages",
                "Twilio rejected these credentials for messages. Check that the Account SID and secret are "
                "correct, and if this is a Restricted API key, give it read access to messages.",
            ),
        ],
    )
    def test_denied_schema_message_names_the_cause(self, schema_name, expected_message):
        with scripted_network(_status(401)):
            is_valid, msg = validate_credentials(API_KEY_AUTH, ACCOUNT_SID, schema_name)
        assert (is_valid, msg) == (False, expected_message)

    def test_chosen_schema_reports_a_server_error_as_such(self):
        # Reporting a Twilio outage on a chosen table as a permission problem would send the user off
        # to rebuild a working API key.
        with scripted_network(_status(503)):
            is_valid, msg = validate_credentials(API_KEY_AUTH, ACCOUNT_SID, "messages")
        assert (is_valid, msg) == (False, _unexpected_status_message(503))

    @pytest.mark.parametrize("schema_name", [None, "messages"])
    def test_transport_error_is_not_valid(self, schema_name):
        # validate_via_probe swallows the exception; the source must report "not validated".
        with scripted_network(always(ConnectionError("boom"))) as network:
            is_valid, msg = validate_credentials((ACCOUNT_SID, "token"), ACCOUNT_SID, schema_name)

        assert (is_valid, msg) == (False, TWILIO_UNREACHABLE_MESSAGE)
        assert len({request.path for request in network.requests_log}) == 1

    def test_probe_candidates_are_real_endpoints(self):
        # A typo here raises KeyError out of validate_credentials and 500s source creation.
        assert set(CREDENTIAL_PROBE_ENDPOINTS) <= set(TWILIO_ENDPOINTS)

    def test_create_denial_message_names_restricted_key_scope(self):
        # Only three of the eleven tables have a probe rung, so a Restricted key scoped elsewhere
        # lands here and the message has to name scope alongside the SID, secret, and region causes.
        assert "Restricted API key" in TWILIO_INVALID_CREDENTIALS_MESSAGE

    def test_picker_reason_is_a_fragment(self):
        # The schema picker interpolates this into "...cannot read this table: {reason}. Grant the
        # missing scope...", so a trailing period doubles up and a full sentence reads as two.
        assert not TWILIO_MAIN_KEY_REQUIRED_REASON.endswith(".")
        assert TWILIO_MAIN_KEY_REQUIRED_REASON.count(".") == 0


class TestPagination:
    def test_paginates_via_next_page_uri_and_saves_absolute_state(self):
        result = _run(
            "messages",
            [
                _response(
                    {
                        "messages": [{"sid": "SM1"}, {"sid": "SM2"}],
                        "next_page_uri": "/2010-04-01/Accounts/x/Messages.json?Page=1",
                    }
                ),
                _response({"messages": [{"sid": "SM3"}], "next_page_uri": None}),
            ],
        )

        assert [r["sid"] for r in result.rows] == ["SM1", "SM2", "SM3"]
        assert len(result.requests) == 2
        # First page targets the account resource path with the default page size.
        first, second = result.requests
        assert first.origin + first.path == f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/Messages.json"
        assert first.param("PageSize") == "1000"
        # Second page follows the self-contained absolute next link, dropping the original params.
        assert second.url == "https://api.twilio.com/2010-04-01/Accounts/x/Messages.json?Page=1"
        assert dict(second.query) == {"Page": ("1",)}
        # State saved once, after the first page is yielded, pointing at the absolute next URL.
        assert result.saved_states == [
            TwilioResumeConfig(next_url="https://api.twilio.com/2010-04-01/Accounts/x/Messages.json?Page=1")
        ]

    def test_verify_endpoint_targets_its_host_and_paginates_via_meta(self):
        # The Verify API lives on its own host and paginates on absolute `meta.next_page_url` rather
        # than the legacy root-relative `next_page_uri`. Getting either wrong makes Verify tables
        # unreachable (wrong host) or stops the sync after page one (missed next link).
        next_url = "https://verify.twilio.com/v2/Services?Page=1&PageToken=abc"
        result = _run(
            "verification_services",
            [
                _response({"services": [{"sid": "VA1"}], "meta": {"next_page_url": next_url}}),
                _response({"services": [{"sid": "VA2"}], "meta": {"next_page_url": None}}),
            ],
        )

        assert [r["sid"] for r in result.rows] == ["VA1", "VA2"]
        assert result.requests[0].origin + result.requests[0].path == "https://verify.twilio.com/v2/Services"
        assert result.requests[1].url == next_url
        assert result.saved_states == [TwilioResumeConfig(next_url=next_url)]

    def test_accounts_reads_the_accounts_root_and_drops_auth_tokens(self):
        # Each subaccount row carries its live Auth Token. The list also sits outside the
        # /Accounts/{SID}/ prefix that every other legacy table uses.
        result = _run(
            "accounts",
            [
                _response(
                    {
                        "accounts": [
                            {"sid": ACCOUNT_SID, "owner_account_sid": ACCOUNT_SID, "auth_token": "fake-token-1"},
                            {"sid": "AC11111111111111111111111111111111", "owner_account_sid": ACCOUNT_SID},
                        ],
                        "next_page_uri": "/2010-04-01/Accounts.json?PageSize=1000&Page=1&PageToken=PAfake",
                    }
                ),
                _response(
                    {
                        "accounts": [
                            {
                                "sid": "AC22222222222222222222222222222222",
                                "owner_account_sid": ACCOUNT_SID,
                                "auth_token": "fake-token-2",
                            }
                        ],
                        "next_page_uri": None,
                    }
                ),
            ],
        )

        assert result.rows == [
            {"sid": ACCOUNT_SID, "owner_account_sid": ACCOUNT_SID},
            {"sid": "AC11111111111111111111111111111111", "owner_account_sid": ACCOUNT_SID},
            {"sid": "AC22222222222222222222222222222222", "owner_account_sid": ACCOUNT_SID},
        ]
        first, second = result.requests
        assert first.origin + first.path == "https://api.twilio.com/2010-04-01/Accounts.json"
        assert second.url == "https://api.twilio.com/2010-04-01/Accounts.json?PageSize=1000&Page=1&PageToken=PAfake"

    def test_resumes_from_saved_state(self):
        resume_url = "https://api.twilio.com/2010-04-01/Accounts/x/Messages.json?Page=5"

        result = _run(
            "messages",
            [_response({"messages": [{"sid": "SM9"}], "next_page_uri": None})],
            resume_state=TwilioResumeConfig(next_url=resume_url),
        )

        assert [r["sid"] for r in result.rows] == ["SM9"]
        # The resumed run starts at the saved next-page link, not the base path.
        assert result.requests[0].url == resume_url
        assert dict(result.requests[0].query) == {"Page": ("5",)}

    def test_incremental_filter_param_is_sent_on_first_request(self):
        result = _run(
            "messages",
            [_response({"messages": [{"sid": "SM1"}], "next_page_uri": None})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="date_sent",
        )

        assert result.requests[0].param("DateSent>") == "2026-03-04"
