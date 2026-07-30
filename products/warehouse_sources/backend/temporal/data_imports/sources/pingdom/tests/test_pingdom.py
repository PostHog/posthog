import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.pingdom import (
    PingdomResumeConfig,
    _to_epoch,
    pingdom_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.settings import (
    ENDPOINTS,
    PINGDOM_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the pingdom module.
PINGDOM_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.pingdom.make_tracked_session"
)


def _nest(data_key: str, items: Any) -> dict[str, Any]:
    body: Any = items
    for key in reversed(data_key.split(".")):
        body = {key: body}
    return body


def _response(endpoint: str, items: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(_nest(PINGDOM_ENDPOINTS[endpoint].data_key, items)).encode()
    return resp


def _make_manager(resume_state: PingdomResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestToEpoch:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp())),
            ("not-a-number", None),
            (True, None),
        ],
    )
    def test_to_epoch_values(self, value, expected):
        assert _to_epoch(value) == expected


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        page_size = PINGDOM_ENDPOINTS["alerts"].page_size
        full_page = [{"time": i} for i in range(page_size)]
        params = _wire(session, [_response("alerts", full_page), _response("alerts", [{"time": page_size}])])

        manager = _make_manager()
        rows = _rows(pingdom_source("token", "alerts", team_id=1, job_id="j", resumable_source_manager=manager))

        assert len(rows) == page_size + 1
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == page_size
        assert params[1]["offset"] == page_size
        # Checkpoint saved once, after the first full page, pointing at the next offset.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == PingdomResumeConfig(offset=page_size)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checks_uses_large_page_size(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response("checks", [{"id": 1}])])

        _rows(pingdom_source("token", "checks", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert params[0]["limit"] == 25000

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response("checks", [{"id": 1}])])

        manager = _make_manager(PingdomResumeConfig(offset=50000))
        _rows(pingdom_source("token", "checks", team_id=1, job_id="j", resumable_source_manager=manager))

        assert params[0]["offset"] == 50000

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_extracts_nested_alerts_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("alerts", [{"time": 1}, {"time": 2}])])

        rows = _rows(pingdom_source("token", "alerts", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert [r["time"] for r in rows] == [1, 2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_request_includes_from_filter(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response("alerts", [])])

        _rows(
            pingdom_source(
                "token",
                "alerts",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
            )
        )
        assert params[0]["from"] == 1700000000

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_has_no_from_filter(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response("alerts", [])])

        _rows(pingdom_source("token", "alerts", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert "from" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_stops_without_saving_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("checks", [])])

        manager = _make_manager()
        rows = _rows(pingdom_source("token", "checks", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"actions": {}},
            {"actions": {"alerts": None}},
            {"actions": None},
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_or_absent_nested_key_yields_no_rows(self, MockSession, body) -> None:
        session = MockSession.return_value
        resp = Response()
        resp.status_code = 200
        resp._content = json.dumps(body).encode()
        _wire(session, [resp])

        manager = _make_manager()
        rows = _rows(pingdom_source("token", "alerts", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == []
        manager.save_state.assert_not_called()


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(PINGDOM_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("token") is expected

    @mock.patch(PINGDOM_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestPingdomSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, endpoint):
        config = PINGDOM_ENDPOINTS[endpoint]
        response = pingdom_source("token", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_alerts_flag_duplicate_primary_keys(self, MockSession):
        response = pingdom_source("token", "alerts", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.has_duplicate_primary_keys is True

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checks_do_not_flag_duplicate_primary_keys(self, MockSession):
        response = pingdom_source("token", "checks", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.has_duplicate_primary_keys is None

    @pytest.mark.parametrize("config", list(PINGDOM_ENDPOINTS.values()))
    def test_partition_keys_are_stable_fields(self, config):
        if config.partition_key:
            # Alert timestamps are immutable event times.
            assert config.partition_key == "time"
