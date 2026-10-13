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


class TestOpnPaymentsSourceIncremental:
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
    def test_resumes_from_saved_offset(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response(_envelope([{"id": "9"}], offset=200, total=201))])

        _rows(_source("Charges", _make_manager(OpnPaymentsResumeConfig(offset=200))))

        assert params[0]["offset"] == 200
