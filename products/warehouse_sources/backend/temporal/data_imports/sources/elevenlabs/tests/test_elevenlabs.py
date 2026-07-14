from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.elevenlabs import (
    ElevenLabsResumeConfig,
    _to_epoch,
    elevenlabs_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.settings import ENDPOINTS

TRACKED_SESSION_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.elevenlabs.make_tracked_session"
)


def _make_manager(resume_state: ElevenLabsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _resp(json_body: Any, status: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = json_body
    resp.status_code = status
    resp.ok = status < 400
    return resp


def _requests(mock_session: mock.MagicMock) -> list[tuple[str, dict[str, list[str]]]]:
    """Return (path, parsed query params) for every GET the transport issued."""
    calls = []
    for call in mock_session.return_value.get.call_args_list:
        url = call.args[0]
        parts = urlsplit(url)
        calls.append((parts.path, parse_qs(parts.query)))
    return calls


class TestToEpoch:
    @parameterized.expand(
        [
            ("none", None, None),
            ("bool_true", True, None),
            ("int", 1700000000, 1700000000),
            ("float", 1700000000.9, 1700000000),
            ("numeric_string", "1700000000", 1700000000),
            ("non_numeric_string", "not-a-number", None),
            ("aware_datetime", datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            ("date", date(2023, 11, 14), 1699920000),
        ]
    )
    def test_to_epoch(self, _name: str, value: Any, expected: int | None) -> None:
        assert _to_epoch(value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok_200", 200, {}, True),
            # A genuine key that merely lacks the user_read permission must pass source-create.
            ("missing_permissions", 401, {"detail": {"status": "missing_permissions", "message": "..."}}, True),
            ("invalid_api_key", 401, {"detail": {"status": "invalid_api_key", "message": "..."}}, False),
            ("unexpected_detail_shape", 401, {"detail": "unexpected shape"}, False),
            ("forbidden", 403, {}, False),
            ("server_error", 500, {}, False),
        ]
    )
    @mock.patch(TRACKED_SESSION_PATH)
    def test_status_mapping(
        self, _name: str, status_code: int, body: dict[str, Any], expected: bool, mock_session: mock.MagicMock
    ) -> None:
        mock_session.return_value.get.return_value = _resp(body, status=status_code)
        assert validate_credentials("key") is expected

    @mock.patch(TRACKED_SESSION_PATH)
    def test_swallows_exceptions(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False

    @mock.patch(TRACKED_SESSION_PATH)
    def test_non_json_401_is_invalid(self, mock_session: mock.MagicMock) -> None:
        resp = _resp({}, status=401)
        resp.json.side_effect = ValueError("not json")
        mock_session.return_value.get.return_value = resp
        assert validate_credentials("key") is False


class TestGetRowsPagination:
    @parameterized.expand(
        [
            (
                "history",
                "history",
                "start_after_history_item_id",
                {"history": [{"history_item_id": "h2"}], "last_history_item_id": "h2", "has_more": False},
            ),
            (
                "conversations",
                "conversations",
                "cursor",
                {"conversations": [{"conversation_id": "c2"}], "next_cursor": None, "has_more": False},
            ),
            (
                "agents",
                "agents",
                "cursor",
                {"agents": [{"agent_id": "a2"}], "next_cursor": None, "has_more": False},
            ),
            (
                "voices",
                "voices",
                "next_page_token",
                {"voices": [{"voice_id": "v2"}], "next_page_token": None, "has_more": False},
            ),
        ]
    )
    @mock.patch(TRACKED_SESSION_PATH)
    def test_each_cursor_style_paginates_with_its_own_params(
        self,
        endpoint: str,
        data_key: str,
        cursor_param: str,
        page_two_body: dict[str, Any],
        mock_session: mock.MagicMock,
    ) -> None:
        cursor_response_key = {
            "history": "last_history_item_id",
            "conversations": "next_cursor",
            "agents": "next_cursor",
            "voices": "next_page_token",
        }[endpoint]
        page_one = {data_key: [{"id": "first"}], cursor_response_key: "cursor-1", "has_more": True}
        mock_session.return_value.get.side_effect = [_resp(page_one), _resp(page_two_body)]

        manager = _make_manager()
        batches = list(get_rows("key", endpoint, mock.MagicMock(), manager))

        assert len(batches) == 2
        requests = _requests(mock_session)
        # First request carries no cursor; the second passes the returned cursor back in the
        # endpoint family's own query param.
        assert cursor_param not in requests[0][1]
        assert requests[1][1][cursor_param] == ["cursor-1"]
        # State is saved once, after the first page was yielded, pointing at page two.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].cursor == "cursor-1"

    @mock.patch(TRACKED_SESSION_PATH)
    def test_models_bare_list_single_fetch(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _resp([{"model_id": "eleven_v3"}])

        manager = _make_manager()
        batches = list(get_rows("key", "models", mock.MagicMock(), manager))

        assert batches == [[{"model_id": "eleven_v3"}]]
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(TRACKED_SESSION_PATH)
    def test_stops_when_has_more_false_even_with_cursor_present(self, mock_session: mock.MagicMock) -> None:
        # /v1/history always echoes last_history_item_id; without the has_more check the
        # transport would refetch the last page forever.
        body = {"history": [{"history_item_id": "h1"}], "last_history_item_id": "h1", "has_more": False}
        mock_session.return_value.get.return_value = _resp(body)

        batches = list(get_rows("key", "history", mock.MagicMock(), _make_manager()))

        assert len(batches) == 1
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(TRACKED_SESSION_PATH)
    def test_empty_page_yields_nothing(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _resp({"history": [], "has_more": False})

        batches = list(get_rows("key", "history", mock.MagicMock(), _make_manager()))

        assert batches == []

    @mock.patch(TRACKED_SESSION_PATH)
    def test_resumes_from_saved_cursor(self, mock_session: mock.MagicMock) -> None:
        body = {"conversations": [{"conversation_id": "c9"}], "next_cursor": None, "has_more": False}
        mock_session.return_value.get.return_value = _resp(body)

        manager = _make_manager(ElevenLabsResumeConfig(cursor="saved-cursor"))
        batches = list(get_rows("key", "conversations", mock.MagicMock(), manager))

        assert [row["conversation_id"] for batch in batches for row in batch] == ["c9"]
        requests = _requests(mock_session)
        assert requests[0][1]["cursor"] == ["saved-cursor"]


class TestGetRowsIncremental:
    @mock.patch(TRACKED_SESSION_PATH)
    def test_history_passes_server_side_filter_and_ascending_sort(self, mock_session: mock.MagicMock) -> None:
        body = {"history": [{"history_item_id": "h1", "date_unix": 1700000100}], "has_more": False}
        mock_session.return_value.get.return_value = _resp(body)

        list(
            get_rows(
                "key",
                "history",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
                incremental_field="date_unix",
            )
        )

        _, params = _requests(mock_session)[0]
        assert params["date_after_unix"] == ["1700000000"]
        assert params["sort_direction"] == ["asc"]

    @mock.patch(TRACKED_SESSION_PATH)
    def test_conversations_passes_call_start_after_unix(self, mock_session: mock.MagicMock) -> None:
        body = {"conversations": [], "has_more": False}
        mock_session.return_value.get.return_value = _resp(body)

        list(
            get_rows(
                "key",
                "conversations",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
                incremental_field="start_time_unix_secs",
            )
        )

        _, params = _requests(mock_session)[0]
        assert params["call_start_after_unix"] == ["1700000000"]

    @mock.patch(TRACKED_SESSION_PATH)
    def test_descending_pagination_stops_once_page_predates_watermark(self, mock_session: mock.MagicMock) -> None:
        # If ElevenLabs silently ignored call_start_after_unix, cursor pagination would walk the
        # full conversation history on every incremental sync. The client-side guard must stop
        # after the first page that is entirely older than the watermark.
        stale_page = {
            "conversations": [{"conversation_id": "old", "start_time_unix_secs": 1600000000}],
            "next_cursor": "more",
            "has_more": True,
        }
        mock_session.return_value.get.return_value = _resp(stale_page)

        batches = list(
            get_rows(
                "key",
                "conversations",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
                incremental_field="start_time_unix_secs",
            )
        )

        # The stale page is still yielded (merge dedupes it) but pagination stops there.
        assert len(batches) == 1
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(TRACKED_SESSION_PATH)
    def test_descending_pagination_keeps_walking_without_watermark(self, mock_session: mock.MagicMock) -> None:
        pages = [
            _resp(
                {
                    "conversations": [{"conversation_id": "new", "start_time_unix_secs": 1700000000}],
                    "next_cursor": "c1",
                    "has_more": True,
                }
            ),
            _resp(
                {
                    "conversations": [{"conversation_id": "old", "start_time_unix_secs": 1600000000}],
                    "next_cursor": None,
                    "has_more": False,
                }
            ),
        ]
        mock_session.return_value.get.side_effect = pages

        batches = list(get_rows("key", "conversations", mock.MagicMock(), _make_manager()))

        assert len(batches) == 2

    @mock.patch(TRACKED_SESSION_PATH)
    def test_ascending_history_never_triggers_watermark_stop(self, mock_session: mock.MagicMock) -> None:
        # date_after_unix is inclusive, so page one re-includes the boundary row whose value
        # equals the watermark. An asc endpoint must never be cut short by the desc guard.
        pages = [
            _resp(
                {
                    "history": [{"history_item_id": "boundary", "date_unix": 1700000000}],
                    "last_history_item_id": "boundary",
                    "has_more": True,
                }
            ),
            _resp(
                {
                    "history": [{"history_item_id": "newer", "date_unix": 1700000500}],
                    "last_history_item_id": "newer",
                    "has_more": False,
                }
            ),
        ]
        mock_session.return_value.get.side_effect = pages

        batches = list(
            get_rows(
                "key",
                "history",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
                incremental_field="date_unix",
            )
        )

        assert len(batches) == 2


class TestElevenLabsSource:
    def test_endpoints_inventory(self) -> None:
        assert ENDPOINTS == ("history", "conversations", "agents", "voices", "models")

    @parameterized.expand(
        [
            ("history", "history_item_id", "date_unix", "asc"),
            ("conversations", "conversation_id", "start_time_unix_secs", "desc"),
            ("agents", "agent_id", "created_at_unix_secs", "desc"),
            ("voices", "voice_id", None, "desc"),
            ("models", "model_id", None, "desc"),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_key: str, partition_key: str | None, sort_mode: str
    ) -> None:
        response = elevenlabs_source("key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [primary_key]
        assert response.sort_mode == sort_mode
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
