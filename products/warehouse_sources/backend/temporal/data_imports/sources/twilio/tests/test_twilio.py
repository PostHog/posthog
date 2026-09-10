import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.settings import TWILIO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.twilio import (
    CREDENTIAL_PROBE_ENDPOINTS,
    TWILIO_ACCOUNT_NOT_FOUND_MESSAGE,
    TWILIO_INVALID_CREDENTIALS_MESSAGE,
    TWILIO_MAIN_KEY_REQUIRED_MESSAGE,
    TWILIO_MAIN_KEY_REQUIRED_REASON,
    TWILIO_UNREACHABLE_MESSAGE,
    TwilioResumeConfig,
    _build_initial_params,
    _format_filter_date,
    _unexpected_status_message,
    twilio_source,
    validate_credentials,
)

ACCOUNT_SID = "AC00000000000000000000000000000000"
# A Standard API key, the credential the source's caption recommends.
API_KEY_AUTH = ("SK00000000000000000000000000000000", "secret")

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the twilio module.
TWILIO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.twilio.twilio.make_tracked_session"
)


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's url+params AT SEND TIME.

    ``request.params``/``request.url`` are mutated in place across pages, so inspecting them after
    the run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _make_manager(resume_state: TwilioResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return twilio_source(
        auth=(ACCOUNT_SID, "token"),
        account_sid=ACCOUNT_SID,
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


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
    @pytest.mark.parametrize(
        "endpoint,expected",
        [
            ("messages", {"PageSize": 1000}),
            # Twilio answers PageSize=1000 on Verify with a 400, so neither Verify endpoint sends
            # one; a page size we don't send can't be rejected.
            ("verification_services", {}),
            ("verification_attempts", {}),
        ],
    )
    def test_full_refresh_sends_only_the_endpoints_page_size(self, endpoint: str, expected: dict[str, Any]):
        params = _build_initial_params(
            TWILIO_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params == expected

    def test_incremental_adds_inclusive_date_filter(self):
        params = _build_initial_params(
            TWILIO_ENDPOINTS["messages"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="date_sent",
        )
        assert params["DateSent>"] == "2026-03-04"

    def test_incremental_honors_chosen_field(self):
        params = _build_initial_params(
            TWILIO_ENDPOINTS["calls"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="end_time",
        )
        assert "EndTime>" in params
        assert "StartTime>" not in params

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
    @mock.patch(TWILIO_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, schema_name, expected_valid):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        is_valid, _msg = validate_credentials((ACCOUNT_SID, "token"), ACCOUNT_SID, schema_name)
        assert is_valid is expected_valid

    @mock.patch(TWILIO_SESSION_PATCH)
    def test_standard_api_key_denied_the_account_resource_is_still_accepted(self, mock_session):
        # Twilio 401s the Accounts resource for Standard and Restricted API keys, so probing it at
        # source-create time rejected the credential the caption recommends.
        def _get(url, **kwargs):
            status = 401 if url.endswith(f"Accounts/{ACCOUNT_SID}.json") else 200
            return mock.MagicMock(status_code=status)

        getter = mock_session.return_value.get
        getter.side_effect = _get

        is_valid, msg = validate_credentials(API_KEY_AUTH, ACCOUNT_SID)

        assert (is_valid, msg) == (True, None)
        probed = [call.args[0] for call in getter.call_args_list]
        assert not any(url.endswith(f"Accounts/{ACCOUNT_SID}.json") for url in probed)

    @mock.patch(TWILIO_SESSION_PATCH)
    def test_create_probe_walks_candidates_until_one_is_readable(self, mock_session):
        # A Restricted key scoped to one product area is denied the earlier candidates.
        getter = mock_session.return_value.get
        getter.side_effect = [mock.MagicMock(status_code=s) for s in (401, 401, 200)]

        is_valid, msg = validate_credentials(API_KEY_AUTH, ACCOUNT_SID)

        assert (is_valid, msg) == (True, None)
        probed = [call.args[0] for call in getter.call_args_list]
        assert probed == [
            f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/{TWILIO_ENDPOINTS[name].path}?PageSize=1"
            for name in CREDENTIAL_PROBE_ENDPOINTS
        ]

    @mock.patch(TWILIO_SESSION_PATCH)
    def test_create_probe_rejects_when_every_candidate_is_denied(self, mock_session):
        getter = mock_session.return_value.get
        getter.return_value = mock.MagicMock(status_code=401)

        is_valid, msg = validate_credentials(API_KEY_AUTH, ACCOUNT_SID)

        assert (is_valid, msg) == (False, TWILIO_INVALID_CREDENTIALS_MESSAGE)
        assert getter.call_count == len(CREDENTIAL_PROBE_ENDPOINTS)

    @pytest.mark.parametrize(
        "status_code, expected_message",
        [
            (500, "Twilio returned an unexpected status (500) while validating credentials."),
            (429, "Twilio returned an unexpected status (429) while validating credentials."),
            (404, TWILIO_ACCOUNT_NOT_FOUND_MESSAGE),
        ],
    )
    @mock.patch(TWILIO_SESSION_PATCH)
    def test_create_probe_stops_on_a_status_that_is_not_a_denial(self, mock_session, status_code, expected_message):
        # A throttle, a server error, or a missing account is not a verdict on the credential, so the
        # remaining candidates must not be walked.
        getter = mock_session.return_value.get
        getter.return_value = mock.MagicMock(status_code=status_code)

        is_valid, msg = validate_credentials(API_KEY_AUTH, ACCOUNT_SID)

        assert (is_valid, msg) == (False, expected_message)
        assert getter.call_count == 1

    @pytest.mark.parametrize(
        "schema_name, expected_url",
        [
            ("messages", f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/Messages.json?PageSize=1"),
            # A Verify table is probed on its own host at its non-account path — not the Account API.
            ("verification_services", "https://verify.twilio.com/v2/Services?PageSize=1"),
        ],
    )
    @mock.patch(TWILIO_SESSION_PATCH)
    def test_specific_schema_probes_endpoint_path(self, mock_session, schema_name, expected_url):
        getter = mock_session.return_value.get
        getter.return_value = mock.MagicMock(status_code=200)
        validate_credentials((ACCOUNT_SID, "token"), ACCOUNT_SID, schema_name)
        assert getter.call_args.args[0] == expected_url

    @pytest.mark.parametrize(
        "schema_name, expected_message",
        [
            ("keys", TWILIO_MAIN_KEY_REQUIRED_MESSAGE),
            (
                "messages",
                "Twilio rejected these credentials for messages. Check that the Account SID and secret are "
                "correct, and if this is a Restricted API key, give it read access to messages.",
            ),
        ],
    )
    @mock.patch(TWILIO_SESSION_PATCH)
    def test_denied_schema_message_names_the_cause(self, mock_session, schema_name, expected_message):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        is_valid, msg = validate_credentials(API_KEY_AUTH, ACCOUNT_SID, schema_name)
        assert (is_valid, msg) == (False, expected_message)

    @mock.patch(TWILIO_SESSION_PATCH)
    def test_chosen_schema_reports_a_server_error_as_such(self, mock_session):
        # Reporting a Twilio outage on a chosen table as a permission problem would send the user off
        # to rebuild a working API key.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=503)
        is_valid, msg = validate_credentials(API_KEY_AUTH, ACCOUNT_SID, "messages")
        assert (is_valid, msg) == (False, _unexpected_status_message(503))

    @pytest.mark.parametrize("schema_name", [None, "messages"])
    @mock.patch(TWILIO_SESSION_PATCH)
    def test_transport_error_is_not_valid(self, mock_session, schema_name):
        # validate_via_probe swallows the exception; the source must report "not validated".
        getter = mock_session.return_value.get
        getter.side_effect = Exception("boom")

        is_valid, msg = validate_credentials((ACCOUNT_SID, "token"), ACCOUNT_SID, schema_name)

        assert (is_valid, msg) == (False, TWILIO_UNREACHABLE_MESSAGE)
        assert getter.call_count == 1

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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_next_page_uri_and_saves_absolute_state(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(
            session,
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
        manager = _make_manager()

        rows = _rows(_source("messages", manager))

        assert [r["sid"] for r in rows] == ["SM1", "SM2", "SM3"]
        assert session.send.call_count == 2
        # First page targets the account resource path with the default page size.
        assert snapshots[0]["url"] == f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/Messages.json"
        assert snapshots[0]["params"]["PageSize"] == 1000
        # Second page follows the self-contained absolute next link, dropping the original params.
        assert snapshots[1]["url"] == "https://api.twilio.com/2010-04-01/Accounts/x/Messages.json?Page=1"
        assert snapshots[1]["params"] == {}
        # State saved once, after the first page is yielded, pointing at the absolute next URL.
        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, TwilioResumeConfig)
        assert saved.next_url == "https://api.twilio.com/2010-04-01/Accounts/x/Messages.json?Page=1"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_verify_endpoint_targets_its_host_and_paginates_via_meta(self, MockSession):
        # The Verify API lives on its own host and paginates on absolute `meta.next_page_url` rather
        # than the legacy root-relative `next_page_uri`. Getting either wrong makes Verify tables
        # unreachable (wrong host) or stops the sync after page one (missed next link).
        session = MockSession.return_value
        next_url = "https://verify.twilio.com/v2/Services?Page=1&PageToken=abc"
        snapshots = _wire(
            session,
            [
                _response({"services": [{"sid": "VA1"}], "meta": {"next_page_url": next_url}}),
                _response({"services": [{"sid": "VA2"}], "meta": {"next_page_url": None}}),
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("verification_services", manager))

        assert [r["sid"] for r in rows] == ["VA1", "VA2"]
        assert snapshots[0]["url"] == "https://verify.twilio.com/v2/Services"
        assert snapshots[1]["url"] == next_url
        saved = manager.save_state.call_args.args[0]
        assert saved.next_url == next_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        resume_url = "https://api.twilio.com/2010-04-01/Accounts/x/Messages.json?Page=5"
        snapshots = _wire(session, [_response({"messages": [{"sid": "SM9"}], "next_page_uri": None})])
        manager = _make_manager(TwilioResumeConfig(next_url=resume_url))

        rows = _rows(_source("messages", manager))

        assert [r["sid"] for r in rows] == ["SM9"]
        # The resumed run starts at the saved next-page link, not the base path.
        assert snapshots[0]["url"] == resume_url
        assert snapshots[0]["params"] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_terminates_without_checkpoint(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"messages": [], "next_page_uri": None})])
        manager = _make_manager()

        rows = _rows(_source("messages", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filter_param_is_sent_on_first_request(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"messages": [{"sid": "SM1"}], "next_page_uri": None})])

        _rows(
            _source(
                "messages",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
                incremental_field="date_sent",
            )
        )

        assert snapshots[0]["params"]["DateSent>"] == "2026-03-04"


class TestTwilioSource:
    @pytest.mark.parametrize(
        "endpoint, expected_sort, expects_partition, expected_primary_key",
        [
            ("messages", "desc", True, "sid"),
            ("calls", "desc", True, "sid"),
            ("recordings", "desc", True, "sid"),
            ("conferences", "desc", True, "sid"),
            ("addresses", "asc", False, "sid"),
            ("transcriptions", "asc", True, "sid"),
            # Usage records have no `sid`; each category appears once, so it's the primary key.
            ("usage_records", "asc", False, "category"),
            ("verification_services", "asc", True, "sid"),
            ("verification_attempts", "desc", True, "sid"),
        ],
    )
    def test_source_response_shape(self, endpoint, expected_sort, expects_partition, expected_primary_key):
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == [expected_primary_key]
        assert response.sort_mode == expected_sort
        if expects_partition:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["date_created"]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
