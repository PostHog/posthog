import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.settings import TWILIO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.twilio import (
    TwilioResumeConfig,
    _build_initial_params,
    _format_filter_date,
    twilio_source,
    validate_credentials,
)

ACCOUNT_SID = "AC00000000000000000000000000000000"

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
    def test_full_refresh_only_sends_page_size(self):
        params = _build_initial_params(
            TWILIO_ENDPOINTS["messages"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params == {"PageSize": 1000}

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
            (403, None, True),  # valid token, no resource selected yet -> accept
            (403, "messages", False),  # valid token, but no access to the chosen endpoint
            (500, None, False),
        ],
    )
    @mock.patch(TWILIO_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, schema_name, expected_valid):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        is_valid, _msg = validate_credentials((ACCOUNT_SID, "token"), ACCOUNT_SID, schema_name)
        assert is_valid is expected_valid

    @mock.patch(TWILIO_SESSION_PATCH)
    def test_unauthorized_returns_actionable_message(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        is_valid, msg = validate_credentials((ACCOUNT_SID, "token"), ACCOUNT_SID)
        assert is_valid is False
        assert msg is not None and "credentials" in msg.lower()

    @mock.patch(TWILIO_SESSION_PATCH)
    def test_specific_schema_probes_endpoint_path(self, mock_session):
        getter = mock_session.return_value.get
        getter.return_value = mock.MagicMock(status_code=200)
        validate_credentials((ACCOUNT_SID, "token"), ACCOUNT_SID, "messages")
        probed_url = getter.call_args.args[0]
        assert probed_url == f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/Messages.json?PageSize=1"

    @mock.patch(TWILIO_SESSION_PATCH)
    def test_transport_error_is_not_valid(self, mock_session):
        # validate_via_probe swallows the exception; the source must report "not validated".
        mock_session.return_value.get.side_effect = Exception("boom")
        is_valid, _msg = validate_credentials((ACCOUNT_SID, "token"), ACCOUNT_SID)
        assert is_valid is False


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
        "endpoint, expected_sort, expects_partition",
        [
            ("messages", "desc", True),
            ("calls", "desc", True),
            ("recordings", "desc", True),
            ("conferences", "desc", True),
            ("addresses", "asc", False),
            ("transcriptions", "asc", True),
        ],
    )
    def test_source_response_shape(self, endpoint, expected_sort, expects_partition):
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["sid"]
        assert response.sort_mode == expected_sort
        if expects_partition:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["date_created"]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
