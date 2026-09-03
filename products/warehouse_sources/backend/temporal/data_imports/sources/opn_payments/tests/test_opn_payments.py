import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.opn_payments import (
    OpnPaymentsResumeConfig,
    _to_iso8601,
    opn_payments_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.settings import (
    ENDPOINTS,
    OPN_PAYMENTS_ENDPOINTS,
    PARTITION_KEY,
)

# The credential probe builds its own session via make_tracked_session imported into the
# opn_payments module.
SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.opn_payments.make_tracked_session"
)
# `opn_payments_source` leaves `client_config["session"]` unset, so `RESTClient` builds its own
# tracked session via the `make_tracked_session` imported into the rest_client module.
REST_CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _envelope(data: list[dict[str, Any]], offset: int, total: int, limit: int = 100) -> dict[str, Any]:
    return {"object": "list", "data": data, "offset": offset, "limit": limit, "total": total}


def _page(size: int, start_id: int = 0) -> list[dict[str, Any]]:
    return [{"id": f"chrg_{start_id + i}"} for i in range(size)]


def _make_manager(resume_state: OpnPaymentsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after
    the run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock | None = None, **kwargs: Any):
    return opn_payments_source(
        "skey_test_123",
        endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager or _make_manager(),
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestToIso8601:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z"),
        ],
    )
    def test_format(self, value, expected):
        assert _to_iso8601(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Your Opn Payments secret key is invalid. Check the key and try again."),
            (500, False, "Opn Payments API returned status 500."),
        ],
    )
    @mock.patch(SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected_valid, expected_message):
        mock_session.return_value.get.return_value = _response({}, status_code=status_code)

        valid, message = validate_credentials("skey_test_123", "2019-05-29")

        assert valid is expected_valid
        assert message == expected_message

    @mock.patch(SESSION_PATCH)
    def test_probes_account_endpoint_with_basic_auth_and_version_header(self, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=200)

        validate_credentials("skey_test_123", "2019-05-29")

        get_call = mock_session.return_value.get.call_args
        assert get_call.args[0] == "https://api.omise.co/account"
        assert get_call.kwargs["auth"].username == "skey_test_123"
        assert get_call.kwargs["auth"].password == ""
        assert mock_session.call_args.kwargs["headers"]["Omise-Version"] == "2019-05-29"
        assert "skey_test_123" in mock_session.call_args.kwargs["redact_values"]

    @mock.patch(SESSION_PATCH)
    def test_swallows_request_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = ConnectionError("boom")

        valid, message = validate_credentials("skey_test_123", "2019-05-29")

        assert valid is False
        assert message == "Could not reach the Opn Payments API."


class TestOpnPaymentsSourcePagination:
    @mock.patch(REST_CLIENT_SESSION_PATCH)
    def test_walks_full_pages_by_offset_until_a_short_page(self, MockSession):
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response(_envelope(_page(100), offset=0, total=150)),
                _response(_envelope(_page(50, start_id=100), offset=100, total=150)),
            ],
        )

        rows = _rows(_source("Charges"))

        assert len(rows) == 150
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == 100
        assert params[1]["offset"] == 100

    @mock.patch(REST_CLIENT_SESSION_PATCH)
    def test_stops_at_total_even_when_last_page_is_full(self, MockSession):
        # A full (100-item) page whose offset+limit already reaches `total` must not fetch a
        # further (empty) page just to discover the end — the total-based check catches it first.
        session = MockSession.return_value
        _wire(session, [_response(_envelope(_page(100), offset=0, total=100))])

        rows = _rows(_source("Charges"))

        assert len(rows) == 100
        assert session.send.call_count == 1

    @mock.patch(REST_CLIENT_SESSION_PATCH)
    def test_stops_on_short_page_even_without_total(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"object": "list", "data": [{"id": "a"}]})])

        rows = _rows(_source("Customers"))

        assert [row["id"] for row in rows] == ["a"]
        # A single (short) page with no `total` field still ends pagination — no second request.
        assert session.send.call_count == 1

    @mock.patch(REST_CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response(_envelope([], offset=0, total=0))])

        manager = _make_manager()
        batches = list(_source("Refunds", manager).items())

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(REST_CLIENT_SESSION_PATCH)
    def test_always_sends_chronological_order(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response(_envelope([], offset=0, total=0))])

        _rows(_source("Transfers"))

        assert params[0]["order"] == "chronological"

    @mock.patch(REST_CLIENT_SESSION_PATCH)
    def test_omise_version_header_sent(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response(_envelope([], offset=0, total=0))])

        list(_source("Transfers", api_version="2017-11-02").items())

        # The version header is applied onto the session after it's built, not passed to
        # make_tracked_session itself — see RESTClient.__init__'s `session.headers.update(...)`.
        assert session.headers["Omise-Version"] == "2017-11-02"


class TestOpnPaymentsSourceIncremental:
    @mock.patch(REST_CLIENT_SESSION_PATCH)
    def test_incremental_sends_converted_from_filter(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response(_envelope([{"id": "chrg_1"}], offset=0, total=1))])

        _rows(
            _source(
                "Charges",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert params[0]["from"] == "2026-01-01T00:00:00Z"

    @mock.patch(REST_CLIENT_SESSION_PATCH)
    def test_full_refresh_never_sends_from_filter(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response(_envelope([{"id": "chrg_1"}], offset=0, total=1))])

        _rows(
            _source(
                "Charges",
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert "from" not in params[0]

    @mock.patch(REST_CLIENT_SESSION_PATCH)
    def test_incremental_defaults_to_epoch_on_first_sync(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response(_envelope([], offset=0, total=0))])

        _rows(_source("Charges", should_use_incremental_field=True, db_incremental_field_last_value=None))

        assert params[0]["from"] == "1970-01-01T00:00:00Z"


class TestOpnPaymentsSourceResume:
    @mock.patch(REST_CLIENT_SESSION_PATCH)
    def test_saves_offset_after_each_yielded_page(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(_envelope(_page(100), offset=0, total=250)),
                _response(_envelope(_page(100, start_id=100), offset=100, total=250)),
                _response(_envelope(_page(50, start_id=200), offset=200, total=250)),
            ],
        )

        manager = _make_manager()
        _rows(_source("Charges", manager))

        saved = [call.args[0].offset for call in manager.save_state.call_args_list]
        # Checkpoints point at the next unfetched offset; the terminal page saves nothing further.
        assert saved == [100, 200]

    @mock.patch(REST_CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response(_envelope([{"id": "9"}], offset=200, total=201))])

        _rows(_source("Charges", _make_manager(OpnPaymentsResumeConfig(offset=200))))

        assert params[0]["offset"] == 200


class TestOpnPaymentsSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        response = _source(endpoint)

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [PARTITION_KEY]

    @pytest.mark.parametrize("endpoint, config", list(OPN_PAYMENTS_ENDPOINTS.items()))
    def test_endpoints_use_documented_paths(self, endpoint, config):
        assert config.path == f"/{config.table_name}"
