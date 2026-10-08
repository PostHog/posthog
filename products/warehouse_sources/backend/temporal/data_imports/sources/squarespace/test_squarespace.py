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


class TestBuildInitialParams:
    MODIFIED_BEFORE = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

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

    def test_schema_probes_that_endpoint_with_its_version(self) -> None:
        with patch(f"{SQUARESPACE_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _make_response({}, status_code=200)
            validate_credentials("token", schema_name="products")
            url = mock_session.return_value.get.call_args.args[0]
            # products is served from the v2 API.
            assert url == f"{SQUARESPACE_BASE_URL}/v2/commerce/products"


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

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        self._drive("orders", manager, [_page("result", [{"id": "a"}])])
        manager.load_state.assert_not_called()

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
