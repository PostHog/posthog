from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark import (
    POSTMARK_BASE_URL,
    PostmarkResumeConfig,
    get_rows,
    postmark_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.settings import (
    ENDPOINTS,
    POSTMARK_ENDPOINTS,
    POSTMARK_MAX_WINDOW,
)


def _mock_manager(can_resume: bool = False, state: PostmarkResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    manager.save_state = MagicMock()
    return manager


def _mock_response(status_code: int = 200, json_payload: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = json_payload or {}
    response.text = "" if response.ok else "error body"

    def _raise_for_status():
        if not response.ok:
            raise Exception(f"{status_code} Client Error")

    response.raise_for_status.side_effect = _raise_for_status
    return response


def _query_of(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok_200", 200, True),
            ("unauthorized_401", 401, False),
            ("forbidden_403", 403, False),
            ("server_500", 500, False),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark.make_tracked_session")
    def test_validate_credentials(self, _name: str, status_code: int, expected: bool, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(status_code=status_code)
        assert validate_credentials("test-token") is expected

        # Auth token is bound to the session headers; URL is on `.get(...)`.
        session_kwargs = mock_session.call_args.kwargs
        assert session_kwargs["headers"]["X-Postmark-Server-Token"] == "test-token"
        # The token is also masked by value so it never lands in a captured HTTP sample.
        assert session_kwargs["redact_values"] == ("test-token",)
        called_args, _ = mock_session.return_value.get.call_args
        assert called_args[0] == f"{POSTMARK_BASE_URL}/message-streams"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark.make_tracked_session")
    def test_validate_credentials_network_error_returns_false(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("test-token") is False


class TestFlatEndpoint:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark.make_tracked_session")
    def test_message_streams_yields_single_batch(self, mock_session: MagicMock) -> None:
        rows = [{"ID": "outbound", "Name": "Transactional", "CreatedAt": "2026-01-01T00:00:00Z"}]
        mock_session.return_value.get.return_value = _mock_response(json_payload={"MessageStreams": rows})

        tables = list(get_rows("test-token", "message_streams", MagicMock(), _mock_manager()))

        assert len(tables) == 1
        assert tables[0].num_rows == 1
        assert tables[0].column("ID").to_pylist() == ["outbound"]

        # The sync session masks the token by value to keep it out of captured HTTP samples.
        assert mock_session.call_args.kwargs["redact_values"] == ("test-token",)

        # Flat endpoints fetch the bare path with no pagination params.
        called_url = mock_session.return_value.get.call_args[0][0]
        assert called_url == f"{POSTMARK_BASE_URL}/message-streams"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark.make_tracked_session")
    def test_flat_endpoint_empty_response_yields_nothing(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(json_payload={"MessageStreams": []})

        tables = list(get_rows("test-token", "message_streams", MagicMock(), _mock_manager()))

        assert tables == []


class TestOffsetPagination:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark.make_tracked_session")
    def test_paginates_until_short_page_and_saves_state(self, mock_session: MagicMock) -> None:
        # First page is full (500 rows) so we ask for a second; second page is short -> stop.
        page1 = [{"MessageID": f"m{i}", "ReceivedAt": "2026-01-01T00:00:00Z"} for i in range(500)]
        page2 = [{"MessageID": f"m{i}", "ReceivedAt": "2026-01-01T00:00:00Z"} for i in range(500, 510)]

        mock_session.return_value.get.side_effect = [
            _mock_response(json_payload={"TotalCount": 510, "Messages": page1}),
            _mock_response(json_payload={"TotalCount": 510, "Messages": page2}),
        ]

        manager = _mock_manager()
        tables = list(get_rows("test-token", "messages_outbound", MagicMock(), manager))

        assert sum(t.num_rows for t in tables) == 510
        assert mock_session.return_value.get.call_count == 2

        first_q = _query_of(mock_session.return_value.get.call_args_list[0].args[0])
        second_q = _query_of(mock_session.return_value.get.call_args_list[1].args[0])
        assert first_q["offset"] == ["0"] and first_q["count"] == ["500"]
        assert second_q["offset"] == ["500"]

        # State is saved once, after the first (full) page, pointing at the next offset.
        manager.save_state.assert_called_once()
        saved: PostmarkResumeConfig = manager.save_state.call_args[0][0]
        assert saved.next_offset == 500

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark.make_tracked_session")
    def test_single_short_page_does_not_save_state(self, mock_session: MagicMock) -> None:
        page = [{"MessageID": "m1", "ReceivedAt": "2026-01-01T00:00:00Z"}]
        mock_session.return_value.get.return_value = _mock_response(json_payload={"TotalCount": 1, "Messages": page})

        manager = _mock_manager()
        tables = list(get_rows("test-token", "messages_outbound", MagicMock(), manager))

        assert sum(t.num_rows for t in tables) == 1
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark.make_tracked_session")
    def test_resumes_from_saved_offset(self, mock_session: MagicMock) -> None:
        page = [{"MessageID": "m501", "ReceivedAt": "2026-01-01T00:00:00Z"}]
        mock_session.return_value.get.return_value = _mock_response(json_payload={"TotalCount": 501, "Messages": page})

        manager = _mock_manager(can_resume=True, state=PostmarkResumeConfig(next_offset=500))
        list(get_rows("test-token", "messages_outbound", MagicMock(), manager))

        first_q = _query_of(mock_session.return_value.get.call_args_list[0].args[0])
        assert first_q["offset"] == ["500"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark.make_tracked_session")
    def test_stops_at_10k_window_and_warns(self, mock_session: MagicMock) -> None:
        # Every page is full, so pagination would continue forever if not for the window cap.
        full_page = [{"MessageID": f"m{i}", "ReceivedAt": "2026-01-01T00:00:00Z"} for i in range(500)]
        mock_session.return_value.get.return_value = _mock_response(
            json_payload={"TotalCount": 99999, "Messages": full_page}
        )

        manager = _mock_manager()
        logger = MagicMock()
        list(get_rows("test-token", "messages_outbound", logger, manager))

        # 10,000 / 500 = 20 pages, then the loop terminates at the window boundary.
        assert mock_session.return_value.get.call_count == POSTMARK_MAX_WINDOW // 500
        logger.warning.assert_called_once()

        last_q = _query_of(mock_session.return_value.get.call_args_list[-1].args[0])
        assert int(last_q["offset"][0]) + int(last_q["count"][0]) == POSTMARK_MAX_WINDOW


class TestEndpointPrimaryKeys:
    @parameterized.expand(
        [
            ("messages_outbound", "Messages", "MessageID"),
            ("messages_inbound", "InboundMessages", "MessageID"),
            ("bounces", "Bounces", "ID"),
            ("templates", "Templates", "TemplateId"),
            ("message_streams", "MessageStreams", "ID"),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark.make_tracked_session")
    def test_reads_correct_data_key(
        self, endpoint: str, data_key: str, primary_key: str, mock_session: MagicMock
    ) -> None:
        rows = [{primary_key: "x1"}]
        mock_session.return_value.get.return_value = _mock_response(json_payload={data_key: rows, "TotalCount": 1})

        tables = list(get_rows("test-token", endpoint, MagicMock(), _mock_manager()))

        assert len(tables) == 1
        assert tables[0].column(primary_key).to_pylist() == ["x1"]


class TestSourceResponseShape:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = postmark_source("test-token", endpoint, MagicMock(), _mock_manager())

        endpoint_config = POSTMARK_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == [endpoint_config.primary_key]

        if endpoint_config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [endpoint_config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestRetryable:
    @patch("tenacity.nap.time.sleep")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark.make_tracked_session")
    def test_429_retries_until_success(self, mock_session: MagicMock, _mock_sleep: MagicMock) -> None:
        mock_session.return_value.get.side_effect = [
            _mock_response(status_code=429),
            _mock_response(json_payload={"MessageStreams": [{"ID": "outbound"}]}),
        ]

        tables = list(get_rows("test-token", "message_streams", MagicMock(), _mock_manager()))

        assert len(tables) == 1
        assert mock_session.return_value.get.call_count == 2

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark.make_tracked_session")
    def test_401_does_not_retry_and_raises(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(status_code=401)

        with pytest.raises(Exception):
            list(get_rows("test-token", "message_streams", MagicMock(), _mock_manager()))

        assert mock_session.return_value.get.call_count == 1
