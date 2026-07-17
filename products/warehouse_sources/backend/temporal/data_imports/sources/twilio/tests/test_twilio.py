from datetime import UTC, date, datetime

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.settings import TWILIO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.twilio import (
    TwilioResumeConfig,
    _build_initial_params,
    _build_initial_url,
    _format_filter_date,
    get_rows,
    twilio_source,
    validate_credentials,
)

ACCOUNT_SID = "AC00000000000000000000000000000000"


def _mock_response(status_code=200, body=None):
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = body if body is not None else {}
    response.text = "error body"
    return response


def _patch_session(responses):
    session = mock.MagicMock()
    session.get.side_effect = responses
    patcher = mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.twilio.twilio.make_tracked_session",
        return_value=session,
    )
    return patcher, session


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


class TestBuildInitialUrl:
    def test_url_contains_account_sid_path(self):
        url = _build_initial_url(TWILIO_ENDPOINTS["messages"], ACCOUNT_SID, {"PageSize": 1})
        assert url.startswith(f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/Messages.json?")
        assert "PageSize=1" in url

    def test_filter_operator_stays_literal(self):
        url = _build_initial_url(
            TWILIO_ENDPOINTS["messages"], ACCOUNT_SID, {"PageSize": 1000, "DateSent>": "2026-03-04"}
        )
        assert "DateSent>=2026-03-04" in url


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
    def test_status_mapping(self, status_code, schema_name, expected_valid):
        patcher, _ = _patch_session([_mock_response(status_code, {"message": "nope"})])
        with patcher:
            is_valid, _msg = validate_credentials((ACCOUNT_SID, "token"), ACCOUNT_SID, schema_name)
        assert is_valid is expected_valid


class TestGetRows:
    def _manager(self, can_resume=False, state=None):
        manager = mock.MagicMock()
        manager.can_resume.return_value = can_resume
        manager.load_state.return_value = state
        return manager

    def test_paginates_via_next_page_uri_and_saves_state(self):
        responses = [
            _mock_response(
                200,
                {
                    "messages": [{"sid": "SM1"}, {"sid": "SM2"}],
                    "next_page_uri": "/2010-04-01/Accounts/x/Messages.json?Page=1",
                },
            ),
            _mock_response(200, {"messages": [{"sid": "SM3"}], "next_page_uri": None}),
        ]
        patcher, session = _patch_session(responses)
        manager = self._manager()

        with patcher:
            pages = list(
                get_rows(
                    auth=(ACCOUNT_SID, "token"),
                    account_sid=ACCOUNT_SID,
                    endpoint="messages",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )

        assert pages == [[{"sid": "SM1"}, {"sid": "SM2"}], [{"sid": "SM3"}]]
        assert session.get.call_count == 2
        # State saved once, after the first page is yielded, pointing at the absolute next URL.
        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, TwilioResumeConfig)
        assert saved.next_url == "https://api.twilio.com/2010-04-01/Accounts/x/Messages.json?Page=1"

    def test_resumes_from_saved_state(self):
        resume_url = "https://api.twilio.com/2010-04-01/Accounts/x/Messages.json?Page=5"
        responses = [_mock_response(200, {"messages": [{"sid": "SM9"}], "next_page_uri": None})]
        patcher, session = _patch_session(responses)
        manager = self._manager(can_resume=True, state=TwilioResumeConfig(next_url=resume_url))

        with patcher:
            pages = list(
                get_rows(
                    auth=(ACCOUNT_SID, "token"),
                    account_sid=ACCOUNT_SID,
                    endpoint="messages",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )

        assert pages == [[{"sid": "SM9"}]]
        assert session.get.call_args_list[0].args[0] == resume_url

    def test_empty_page_terminates(self):
        responses = [_mock_response(200, {"messages": [], "next_page_uri": None})]
        patcher, _ = _patch_session(responses)
        manager = self._manager()

        with patcher:
            pages = list(
                get_rows(
                    auth=(ACCOUNT_SID, "token"),
                    account_sid=ACCOUNT_SID,
                    endpoint="messages",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )

        assert pages == []
        manager.save_state.assert_not_called()


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
        response = twilio_source(
            auth=(ACCOUNT_SID, "token"),
            account_sid=ACCOUNT_SID,
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["sid"]
        assert response.sort_mode == expected_sort
        if expects_partition:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["date_created"]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
