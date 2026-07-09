import json
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.decagon import (
    DECAGON_BASE_URL,
    DecagonResumeConfig,
    decagon_source,
    get_rows,
    validate_credentials,
)

DECAGON_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.decagon.decagon"


def _make_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _conversation(conversation_id: str) -> dict[str, Any]:
    return {"conversation_id": conversation_id, "created_at": "2026-01-01T00:00:00Z"}


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_code_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        with patch(f"{DECAGON_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _make_response({}, status_code=status_code)
            assert validate_credentials("key") is expected

    def test_network_error_returns_invalid(self) -> None:
        with patch(f"{DECAGON_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("key") is False

    def test_probes_export_endpoint_with_bearer_auth(self) -> None:
        with patch(f"{DECAGON_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _make_response({}, status_code=200)
            validate_credentials("secret-key")
            args, kwargs = mock_session.return_value.get.call_args
            assert args[0] == f"{DECAGON_BASE_URL}/conversation/export"
            assert kwargs["headers"]["Authorization"] == "Bearer secret-key"


class TestGetRows:
    def _drive(self, manager: MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[list[str]]]:
        """Drive get_rows with a mocked session; return (params sent per page, ids yielded per batch)."""
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_get(_url: str, *, params: dict[str, Any], **_kwargs: Any) -> Response:
            sent_params.append(dict(params or {}))
            return next(response_iter)

        with (
            patch(f"{DECAGON_MODULE}.make_tracked_session") as mock_session,
            patch(f"{DECAGON_MODULE}.time.sleep"),
        ):
            mock_session.return_value.get.side_effect = fake_get
            batches = list(
                get_rows(
                    api_key="key",
                    endpoint="conversations",
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                )
            )
        yielded_ids = [[item["conversation_id"] for item in batch] for batch in batches]
        return sent_params, yielded_ids

    def _fresh_manager(self) -> MagicMock:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        return manager

    def test_paginates_with_cursor_and_saves_state_after_each_yield(self) -> None:
        manager = self._fresh_manager()
        responses = [
            _make_response({"conversations": [_conversation("c1")], "next_page_cursor": "cur-1"}),
            _make_response({"conversations": [_conversation("c2")], "next_page_cursor": "cur-2"}),
            _make_response({"conversations": [_conversation("c3")], "next_page_cursor": None}),
        ]
        sent_params, yielded_ids = self._drive(manager, responses)

        # First request omits the cursor (starts at the oldest conversations).
        assert sent_params == [{}, {"cursor": "cur-1"}, {"cursor": "cur-2"}]
        assert yielded_ids == [["c1"], ["c2"], ["c3"]]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [DecagonResumeConfig(cursor="cur-1"), DecagonResumeConfig(cursor="cur-2")]

    def test_resume_seeds_cursor_from_saved_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = DecagonResumeConfig(cursor="cur-resumed")

        responses = [_make_response({"conversations": [_conversation("c9")], "next_page_cursor": None})]
        sent_params, yielded_ids = self._drive(manager, responses)

        assert sent_params == [{"cursor": "cur-resumed"}]
        assert yielded_ids == [["c9"]]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = self._fresh_manager()
        responses = [_make_response({"conversations": [_conversation("c1")], "next_page_cursor": None})]
        self._drive(manager, responses)
        manager.save_state.assert_not_called()

    def test_deduplicates_conversations_that_reappear_in_later_pages(self) -> None:
        # A conversation that receives new messages re-enters the export stream, so the
        # same conversation_id can appear on multiple pages of a single walk.
        manager = self._fresh_manager()
        responses = [
            _make_response({"conversations": [_conversation("c1"), _conversation("c2")], "next_page_cursor": "cur-1"}),
            _make_response({"conversations": [_conversation("c2"), _conversation("c3")], "next_page_cursor": None}),
        ]
        _, yielded_ids = self._drive(manager, responses)
        assert yielded_ids == [["c1", "c2"], ["c3"]]

    def test_stops_when_server_repeats_the_same_cursor(self) -> None:
        manager = self._fresh_manager()
        responses = [
            _make_response({"conversations": [_conversation("c1")], "next_page_cursor": "cur-1"}),
            _make_response({"conversations": [_conversation("c2")], "next_page_cursor": "cur-1"}),
        ]
        sent_params, yielded_ids = self._drive(manager, responses)
        assert len(sent_params) == 2
        assert yielded_ids == [["c1"], ["c2"]]

    def test_empty_page_with_cursor_continues_without_yielding(self) -> None:
        manager = self._fresh_manager()
        responses = [
            _make_response({"conversations": [], "next_page_cursor": "cur-1"}),
            _make_response({"conversations": [_conversation("c1")], "next_page_cursor": None}),
        ]
        sent_params, yielded_ids = self._drive(manager, responses)
        assert sent_params == [{}, {"cursor": "cur-1"}]
        assert yielded_ids == [["c1"]]

    @parameterized.expand([("rate_limited", 429), ("server_error", 500)])
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status_code: int) -> None:
        manager = self._fresh_manager()
        responses = [
            _make_response({}, status_code=status_code),
            _make_response({"conversations": [_conversation("c1")], "next_page_cursor": None}),
        ]
        _, yielded_ids = self._drive(manager, responses)
        assert yielded_ids == [["c1"]]

    def test_unauthorized_raises_without_retry(self) -> None:
        manager = self._fresh_manager()
        response_401 = _make_response({"detail": "Invalid Authorization token."}, status_code=401)
        response_401.url = f"{DECAGON_BASE_URL}/conversation/export"
        try:
            self._drive(manager, [response_401])
            raise AssertionError("expected HTTPError")
        except HTTPError as e:
            assert e.response.status_code == 401


class TestDecagonSource:
    def test_source_response_shape(self) -> None:
        response = decagon_source(
            api_key="key",
            endpoint="conversations",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(spec=ResumableSourceManager),
        )
        assert response.name == "conversations"
        assert response.primary_keys == ["conversation_id"]
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
