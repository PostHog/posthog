import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark import (
    POSTMARK_BASE_URL,
    PostmarkResumeConfig,
    postmark_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.settings import (
    ENDPOINTS,
    POSTMARK_ENDPOINTS,
    POSTMARK_MAX_WINDOW,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the postmark module.
POSTMARK_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark.make_tracked_session"
)


def _response(body: dict[str, Any], *, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = POSTMARK_BASE_URL
    return resp


def _make_manager(resume_state: PostmarkResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response] | Any) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when
    each request is prepared rather than inspecting the final mutated state.
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


def _source(endpoint: str, manager: mock.MagicMock):
    return postmark_source("test-token", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok_200", 200, True),
            ("unauthorized_401", 401, False),
            ("forbidden_403", 403, False),
            ("server_500", 500, False),
        ]
    )
    @mock.patch(POSTMARK_SESSION_PATCH)
    def test_validate_credentials(self, _name: str, status_code: int, expected: bool, mock_session: mock.MagicMock):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("test-token") is expected

        # The probe session masks the token by value so it never lands in a captured HTTP sample.
        assert mock_session.call_args.kwargs["redact_values"] == ("test-token",)
        # The token is carried in the X-Postmark-Server-Token header against /message-streams.
        get_args, get_kwargs = mock_session.return_value.get.call_args
        assert get_args[0] == f"{POSTMARK_BASE_URL}/message-streams"
        assert get_kwargs["headers"]["X-Postmark-Server-Token"] == "test-token"

    @mock.patch(POSTMARK_SESSION_PATCH)
    def test_validate_credentials_network_error_returns_false(self, mock_session: mock.MagicMock):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("test-token") is False


class TestFlatEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_message_streams_yields_single_batch(self, MockSession):
        session = MockSession.return_value
        rows_in = [{"ID": "outbound", "Name": "Transactional", "CreatedAt": "2026-01-01T00:00:00Z"}]
        params = _wire(session, [_response({"MessageStreams": rows_in})])

        rows = _rows(_source("message_streams", _make_manager()))

        assert [r["ID"] for r in rows] == ["outbound"]
        assert session.send.call_count == 1
        # The sync session masks the token by value to keep it out of captured HTTP samples.
        assert MockSession.call_args.kwargs["redact_values"] == ("test-token",)
        # Flat endpoints fetch with no pagination params.
        assert params[0] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_flat_endpoint_empty_response_yields_nothing(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"MessageStreams": []})])

        assert _rows(_source("message_streams", _make_manager())) == []


class TestOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page_and_saves_state(self, MockSession):
        session = MockSession.return_value
        page1 = [{"MessageID": f"m{i}", "ReceivedAt": "2026-01-01T00:00:00Z"} for i in range(500)]
        page2 = [{"MessageID": f"m{i}", "ReceivedAt": "2026-01-01T00:00:00Z"} for i in range(500, 510)]
        params = _wire(
            session,
            [
                _response({"TotalCount": 510, "Messages": page1}),
                _response({"TotalCount": 510, "Messages": page2}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("messages_outbound", manager))

        assert len(rows) == 510
        assert session.send.call_count == 2
        assert params[0]["offset"] == 0 and params[0]["count"] == 500
        assert params[1]["offset"] == 500

        # State is saved once, after the first (full) page, pointing at the next offset.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == PostmarkResumeConfig(next_offset=500)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_short_page_does_not_save_state(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"TotalCount": 1, "Messages": [{"MessageID": "m1"}]})])

        manager = _make_manager()
        rows = _rows(_source("messages_outbound", manager))

        assert len(rows) == 1
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response({"TotalCount": 501, "Messages": [{"MessageID": "m501"}]})])

        manager = _make_manager(PostmarkResumeConfig(next_offset=500))
        _rows(_source("messages_outbound", manager))

        assert params[0]["offset"] == 500

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark.logger")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_at_10k_window_and_warns(self, MockSession, mock_logger):
        session = MockSession.return_value
        # Every page is full, so pagination would continue forever if not for the window cap.
        full_page = [{"MessageID": f"m{i}", "ReceivedAt": "2026-01-01T00:00:00Z"} for i in range(500)]
        params = _wire(session, lambda *a, **k: _response({"TotalCount": 99999, "Messages": full_page}))

        _rows(_source("messages_outbound", _make_manager()))

        # 10,000 / 500 = 20 pages, then the loop terminates at the window boundary.
        assert session.send.call_count == POSTMARK_MAX_WINDOW // 500
        mock_logger.warning.assert_called_once()
        assert params[-1]["offset"] + params[-1]["count"] == POSTMARK_MAX_WINDOW


class TestEndpointDataKeys:
    @parameterized.expand(
        [
            ("messages_outbound", "Messages", "MessageID"),
            ("messages_inbound", "InboundMessages", "MessageID"),
            ("bounces", "Bounces", "ID"),
            ("templates", "Templates", "TemplateId"),
            ("message_streams", "MessageStreams", "ID"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reads_correct_data_key(self, endpoint: str, data_key: str, primary_key: str, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({data_key: [{primary_key: "x1"}], "TotalCount": 1})])

        rows = _rows(_source(endpoint, _make_manager()))

        assert [r[primary_key] for r in rows] == ["x1"]


class TestSourceResponseShape:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, _MockSession):
        response = _source(endpoint, _make_manager())

        config = POSTMARK_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]

        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestRetryable:
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_429_retries_until_success(self, MockSession, _mock_sleep):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({}, status=429),
                _response({"MessageStreams": [{"ID": "outbound"}]}),
            ],
        )

        rows = _rows(_source("message_streams", _make_manager()))

        assert [r["ID"] for r in rows] == ["outbound"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_401_does_not_retry_and_raises(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({}, status=401)])

        with pytest.raises(Exception):
            _rows(_source("message_streams", _make_manager()))

        assert session.send.call_count == 1
