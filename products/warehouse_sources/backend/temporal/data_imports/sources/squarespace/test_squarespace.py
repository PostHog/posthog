import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.squarespace.settings import SQUARESPACE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.squarespace.squarespace import (
    MAX_CURSOR_RESTARTS,
    SQUARESPACE_BASE_URL,
    SquarespaceInvalidCursorError,
    SquarespaceResumeConfig,
    _build_initial_params,
    _clamp_future_value_to_now,
    _format_datetime_z,
    _is_invalid_cursor_error,
    get_rows,
    validate_credentials,
)

SQUARESPACE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.squarespace.squarespace"


def _make_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(data_key: str, items: list[dict[str, Any]], next_cursor: str | None = None) -> Response:
    pagination = {"hasNextPage": next_cursor is not None, "nextPageCursor": next_cursor, "nextPageUrl": None}
    return _make_response({data_key: items, "pagination": pagination})


class TestFormatDatetimeZ:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (
                "microseconds_truncated",
                datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC),
                "2026-01-15T10:30:45.123Z",
            ),
            ("naive_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "2026-03-04T02:58:14.000Z", "2026-03-04T02:58:14.000Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime_z(value) == expected

    def test_no_plus_offset_in_output(self) -> None:
        # Squarespace rejects the +00:00 offset; output must use the Z suffix.
        assert "+00:00" not in _format_datetime_z(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestClampFutureValueToNow:
    def test_future_datetime_clamped(self) -> None:
        now = datetime(2026, 6, 1, tzinfo=UTC)
        assert _clamp_future_value_to_now(datetime(2027, 1, 1, tzinfo=UTC), now) == now

    def test_past_datetime_unchanged(self) -> None:
        now = datetime(2026, 6, 1, tzinfo=UTC)
        past = datetime(2025, 1, 1, tzinfo=UTC)
        assert _clamp_future_value_to_now(past, now) == past

    def test_naive_datetime_treated_as_utc(self) -> None:
        now = datetime(2026, 6, 1, tzinfo=UTC)
        assert _clamp_future_value_to_now(datetime(2027, 1, 1), now) == now


class TestBuildInitialParams:
    MODIFIED_BEFORE = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    def test_incremental_endpoint_sets_window(self) -> None:
        params = _build_initial_params(
            SQUARESPACE_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 5, 1, tzinfo=UTC),
            modified_before=self.MODIFIED_BEFORE,
        )
        # Squarespace requires both window bounds together.
        assert params["modifiedAfter"] == "2026-05-01T00:00:00.000Z"
        assert params["modifiedBefore"] == "2026-06-01T12:00:00.000Z"
        assert "cursor" not in params

    def test_incremental_endpoint_full_refresh_omits_window(self) -> None:
        params = _build_initial_params(
            SQUARESPACE_ENDPOINTS["orders"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            modified_before=self.MODIFIED_BEFORE,
        )
        assert params == {}

    def test_first_incremental_sync_without_last_value_omits_window(self) -> None:
        # supports_incremental but no watermark yet -> scan everything (no window),
        # otherwise we'd send modifiedBefore without modifiedAfter (a 400).
        params = _build_initial_params(
            SQUARESPACE_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            modified_before=self.MODIFIED_BEFORE,
        )
        assert "modifiedAfter" not in params
        assert "modifiedBefore" not in params

    def test_full_refresh_endpoint_never_sets_window(self) -> None:
        # inventory has no server-side time filter, so even with an incremental value
        # selected we must not invent a window param.
        params = _build_initial_params(
            SQUARESPACE_ENDPOINTS["inventory"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 5, 1, tzinfo=UTC),
            modified_before=self.MODIFIED_BEFORE,
        )
        assert "modifiedAfter" not in params
        assert "modifiedBefore" not in params

    def test_extra_params_applied_on_first_page(self) -> None:
        params = _build_initial_params(
            SQUARESPACE_ENDPOINTS["profiles"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            modified_before=self.MODIFIED_BEFORE,
        )
        assert params == {"sortField": "createdOn", "sortDirection": "asc"}

    def test_future_last_value_clamped_into_window(self) -> None:
        params = _build_initial_params(
            SQUARESPACE_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2099, 1, 1, tzinfo=UTC),
            modified_before=self.MODIFIED_BEFORE,
        )
        # modifiedAfter must not exceed modifiedBefore, or Squarespace 400s on an inverted window.
        assert params["modifiedAfter"] == params["modifiedBefore"]


class TestIsInvalidCursorError:
    @parameterized.expand(
        [
            ("cursor_in_message", 400, {"message": "The cursor parameter contains an invalid value"}, True),
            ("cursor_in_subtype", 400, {"subtype": "INVALID_CURSOR", "message": "bad"}, True),
            ("unrelated_400", 400, {"message": "modifiedAfter is not a valid ISO 8601 string"}, False),
            ("empty_400", 400, {}, False),
            ("not_a_400", 404, {"message": "cursor"}, False),
        ]
    )
    def test_detection(self, _name: str, status_code: int, body: dict[str, Any], expected: bool) -> None:
        assert _is_invalid_cursor_error(_make_response(body, status_code=status_code)) is expected

    def test_non_json_body_is_not_invalid_cursor(self) -> None:
        resp = Response()
        resp.status_code = 400
        resp._content = b"<html>Bad Request</html>"
        assert _is_invalid_cursor_error(resp) is False


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, (True, False)),
            ("unauthorized", 401, (False, False)),
            ("forbidden", 403, (False, True)),
            ("server_error", 500, (False, False)),
        ]
    )
    def test_status_code_mapping(self, _name: str, status_code: int, expected: tuple[bool, bool]) -> None:
        with patch(f"{SQUARESPACE_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _make_response({}, status_code=status_code)
            assert validate_credentials("token") == expected

    def test_network_error_returns_invalid(self) -> None:
        with patch(f"{SQUARESPACE_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("token") == (False, False)

    def test_no_schema_probes_orders(self) -> None:
        with patch(f"{SQUARESPACE_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _make_response({}, status_code=200)
            validate_credentials("token")
            url = mock_session.return_value.get.call_args.args[0]
            assert url == f"{SQUARESPACE_BASE_URL}/1.0/commerce/orders"

    def test_schema_probes_that_endpoint_with_its_version(self) -> None:
        with patch(f"{SQUARESPACE_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _make_response({}, status_code=200)
            validate_credentials("token", schema_name="products")
            url = mock_session.return_value.get.call_args.args[0]
            # products is served from the v2 API.
            assert url == f"{SQUARESPACE_BASE_URL}/v2/commerce/products"

    def test_sends_user_agent_header(self) -> None:
        with patch(f"{SQUARESPACE_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _make_response({}, status_code=200)
            validate_credentials("token")
            headers = mock_session.return_value.get.call_args.kwargs["headers"]
            assert headers["User-Agent"]
            assert headers["Authorization"] == "Bearer token"


class TestGetRowsPagination:
    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
        """Drive get_rows with a mocked session, returning (params sent per page, yielded batches)."""
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_get(_url: str, *, params: dict[str, Any], **_kwargs: Any) -> Response:
            sent_params.append(dict(params or {}))
            return next(response_iter)

        with patch(f"{SQUARESPACE_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = fake_get
            batches = list(
                get_rows(
                    api_key="token",
                    endpoint=endpoint,
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                    **kwargs,
                )
            )
        return sent_params, batches

    def test_fresh_run_saves_cursor_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _page("result", [{"id": "o1"}], next_cursor="cur-1"),
            _page("result", [{"id": "o2"}], next_cursor="cur-2"),
            _page("result", [{"id": "o3"}]),
        ]
        sent_params, batches = self._drive("orders", manager, responses)

        # First request carries the query params; subsequent pages carry the cursor only.
        assert "cursor" not in sent_params[0]
        assert sent_params[1] == {"cursor": "cur-1"}
        assert sent_params[2] == {"cursor": "cur-2"}
        assert batches == [[{"id": "o1"}], [{"id": "o2"}], [{"id": "o3"}]]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [SquarespaceResumeConfig(cursor="cur-1"), SquarespaceResumeConfig(cursor="cur-2")]

    def test_resume_seeds_cursor_from_saved_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = SquarespaceResumeConfig(cursor="cur-resumed")

        sent_params, _ = self._drive("orders", manager, [_page("result", [{"id": "o9"}])])

        assert sent_params == [{"cursor": "cur-resumed"}]
        manager.load_state.assert_called_once()

    def test_empty_saved_cursor_starts_from_beginning(self) -> None:
        # An empty cursor (written by a restart) must be treated as "start over", not replayed.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = SquarespaceResumeConfig(cursor="")

        sent_params, _ = self._drive("orders", manager, [_page("result", [{"id": "o1"}])])
        assert "cursor" not in sent_params[0]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        self._drive("orders", manager, [_page("result", [{"id": "only"}])])
        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        self._drive("orders", manager, [_page("result", [{"id": "a"}])])
        manager.load_state.assert_not_called()

    def test_terminates_when_has_next_false_even_with_cursor(self) -> None:
        # hasNextPage=False must stop pagination even if a stray nextPageCursor is present.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        body = {
            "result": [{"id": "o1"}],
            "pagination": {"hasNextPage": False, "nextPageCursor": "should-be-ignored"},
        }
        sent_params, _ = self._drive("orders", manager, [_make_response(body)])
        assert len(sent_params) == 1
        manager.save_state.assert_not_called()

    @parameterized.expand(
        [
            ("orders", "result"),
            ("products", "products"),
            ("transactions", "documents"),
            ("inventory", "inventory"),
            ("store_pages", "storePages"),
            ("profiles", "profiles"),
        ]
    )
    def test_yields_rows_using_endpoint_data_key(self, endpoint: str, data_key: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        _, batches = self._drive(endpoint, manager, [_page(data_key, [{"id": "a"}, {"id": "b"}])])
        assert batches == [[{"id": "a"}, {"id": "b"}]]

    def test_invalid_cursor_restarts_stream_from_beginning(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = SquarespaceResumeConfig(cursor="stale-cursor")

        responses = [
            _make_response({"message": "cursor invalid"}, status_code=400),
            _page("result", [{"id": "o1"}], next_cursor="cur-1"),
            _page("result", [{"id": "o2"}]),
        ]
        sent_params, _ = self._drive("orders", manager, responses)

        assert sent_params[0] == {"cursor": "stale-cursor"}
        assert "cursor" not in sent_params[1]
        assert sent_params[2] == {"cursor": "cur-1"}

    def test_invalid_cursor_restart_evicts_stale_cursor(self) -> None:
        # When the restart finishes within a single page there's no fresh cursor to persist,
        # so the restart must explicitly overwrite the stale cursor.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = SquarespaceResumeConfig(cursor="stale-cursor")

        responses = [
            _make_response({"message": "cursor invalid"}, status_code=400),
            _page("result", [{"id": "o1"}]),
        ]
        self._drive("orders", manager, responses)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [SquarespaceResumeConfig(cursor="")]

    def test_invalid_cursor_on_initial_request_is_surfaced(self) -> None:
        # A cursor-less initial request can't trigger cursor expiry, so a cursor-rejection
        # there is a malformed query — surface it rather than looping forever.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with pytest.raises(SquarespaceInvalidCursorError):
            self._drive("orders", manager, [_make_response({"message": "cursor invalid"}, status_code=400)])

    def test_invalid_cursor_gives_up_after_restart_budget_exhausted(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = SquarespaceResumeConfig(cursor="stale-cursor")

        invalid = _make_response({"message": "cursor invalid"}, status_code=400)
        responses = [invalid]
        for _ in range(MAX_CURSOR_RESTARTS):
            responses.append(_page("result", [{"id": "o"}], next_cursor="cur"))
            responses.append(invalid)
        with pytest.raises(SquarespaceInvalidCursorError):
            self._drive("orders", manager, responses)

    def test_incremental_first_page_sends_window(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        sent_params, _ = self._drive(
            "orders",
            manager,
            [_page("result", [{"id": "o1"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 5, 1, tzinfo=UTC),
        )
        assert sent_params[0]["modifiedAfter"] == "2026-05-01T00:00:00.000Z"
        assert "modifiedBefore" in sent_params[0]
