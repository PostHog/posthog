from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.kernel.kernel import (
    PAGE_SIZE,
    KernelRetryableError,
    KernelUnexpectedResponseError,
    _extract_items,
    _next_page,
    _redact_sensitive_fields,
    get_rows,
    kernel_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kernel.settings import ENDPOINTS, KERNEL_ENDPOINTS

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.kernel.kernel"


def _response(
    items: Any, *, status_code: int = 200, has_more: bool | None = None, next_offset: int | None = None
) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = items
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 400
    resp.text = "error"
    headers: dict[str, str] = {}
    if has_more is not None:
        headers["X-Has-More"] = "true" if has_more else "false"
    if next_offset is not None:
        headers["X-Next-Offset"] = str(next_offset)
    resp.headers = headers
    return resp


class TestExtractItems:
    @pytest.mark.parametrize(
        "body, expected",
        [
            ([{"id": "a"}], [{"id": "a"}]),
            ([], []),
            ({"data": [{"id": "b"}]}, [{"id": "b"}]),
            ({"items": [{"id": "c"}]}, [{"id": "c"}]),
            ({"results": [{"id": "d"}]}, [{"id": "d"}]),
            ({"data": []}, []),
        ],
    )
    def test_recognized_shapes(self, body: Any, expected: list[dict]) -> None:
        assert _extract_items(body) == expected

    @pytest.mark.parametrize("body", [{"unexpected": [{"id": "e"}]}, {}, None, "oops", 42])
    def test_unexpected_shape_raises(self, body: Any) -> None:
        # A body we can't parse must fail loudly - returning [] would let a full refresh
        # overwrite the table with zero rows.
        with pytest.raises(KernelUnexpectedResponseError):
            _extract_items(body)


class TestRedactSensitiveFields:
    def test_strips_credential_bearing_keys_case_insensitively(self) -> None:
        item = {
            "id": "b1",
            "env_vars": {"SECRET": "x"},
            "CDP_WS_URL": "wss://token@example",
            "webdriver_ws_url": "wss://jwt@example",
            "browser_live_view_url": "https://token@example",
            "region": "us",
        }
        assert _redact_sensitive_fields(item) == {"id": "b1", "region": "us"}


class TestNextPage:
    @pytest.mark.parametrize(
        "headers, page_len, expected",
        [
            # Header wins over offset math.
            ({"X-Has-More": "true", "X-Next-Offset": "300"}, 100, (True, 300)),
            ({"X-Has-More": "false"}, 100, (False, 100)),
            # No header: keep paging only while a full page came back.
            ({}, PAGE_SIZE, (True, PAGE_SIZE)),
            ({}, 5, (False, 5)),
            # Malformed next-offset falls back to offset + page_len.
            ({"X-Has-More": "true", "X-Next-Offset": "not-a-number"}, 100, (True, 100)),
        ],
    )
    def test_next_page(self, headers: dict[str, str], page_len: int, expected: tuple[bool, int]) -> None:
        assert _next_page(headers, current_offset=0, page_len=page_len) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_ok",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_status_mapping(self, mock_session: Any, status_code: int, expected_ok: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        ok, status = validate_credentials("sk_test")
        assert ok is expected_ok
        assert status == status_code

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_sends_bearer_auth(self, mock_session: Any) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("sk_test")

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer sk_test"
        # Kernel responses carry secrets the generic sampler can't scrub, so capture must be off.
        assert mock_session.call_args.kwargs["capture"] is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_transport_failure_returns_none_status(self, mock_session: Any) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("sk_test") == (False, None)


class TestGetRows:
    def _collect(self, endpoint: str) -> list[dict]:
        rows: list[dict] = []
        for table in get_rows("sk_test", endpoint, mock.MagicMock()):
            rows.extend(table.to_pylist())
        return rows

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_single_page_full_refresh(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = _response([{"id": "a1"}, {"id": "a2"}], has_more=False)

        rows = self._collect("apps")

        assert rows == [{"id": "a1"}, {"id": "a2"}]
        assert mock_session.return_value.get.call_count == 1
        # Kernel responses carry secrets the generic sampler can't scrub, so capture must be off.
        assert mock_session.call_args.kwargs["capture"] is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_offset_pagination_follows_next_offset_header(self, mock_session: Any) -> None:
        mock_session.return_value.get.side_effect = [
            _response([{"id": "a1"}], has_more=True, next_offset=100),
            _response([{"id": "a2"}], has_more=False),
        ]

        rows = self._collect("deployments")

        assert rows == [{"id": "a1"}, {"id": "a2"}]
        urls = [call.kwargs.get("url") or call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert "offset=0" in urls[0]
        assert "offset=100" in urls[1]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_first_page_yields_nothing(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = _response([], has_more=False)
        assert self._collect("profiles") == []

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_page_with_more_pages_keeps_paging(self, mock_session: Any) -> None:
        # An empty page that still reports X-Has-More must not end the sync early.
        mock_session.return_value.get.side_effect = [
            _response([], has_more=True, next_offset=100),
            _response([{"id": "a1"}], has_more=False),
        ]
        assert self._collect("apps") == [{"id": "a1"}]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_page_without_advancing_offset_terminates(self, mock_session: Any) -> None:
        # Empty page claiming more pages but with no way to advance the offset must stop,
        # not loop forever re-fetching the same request.
        mock_session.return_value.get.return_value = _response([], has_more=True)
        assert self._collect("apps") == []
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_browsers_requests_all_statuses(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = _response([{"id": "b1"}], has_more=False)

        self._collect("browsers")

        url = mock_session.return_value.get.call_args.args[0]
        assert "status=all" in url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_sensitive_fields_are_stripped_from_rows(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = _response(
            [{"id": "b1", "browser_live_view_url": "https://token@example", "region": "us"}], has_more=False
        )

        rows = self._collect("browsers")

        assert rows == [{"id": "b1", "region": "us"}]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_unexpected_response_shape_raises(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = _response({"unexpected": [{"id": "a1"}]}, has_more=False)

        with pytest.raises(KernelUnexpectedResponseError):
            self._collect("apps")

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retries_retryable_status_then_succeeds(self, mock_session: Any, _sleep: Any) -> None:
        mock_session.return_value.get.side_effect = [
            _response(None, status_code=500),
            _response(None, status_code=429),
            _response([{"id": "a1"}], has_more=False),
        ]

        rows = self._collect("apps")

        assert rows == [{"id": "a1"}]
        assert mock_session.return_value.get.call_count == 3

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retries_exhausted_raises(self, mock_session: Any, _sleep: Any) -> None:
        mock_session.return_value.get.return_value = _response(None, status_code=503)

        with pytest.raises(KernelRetryableError):
            self._collect("apps")

        assert mock_session.return_value.get.call_count == 5


class TestKernelSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = KERNEL_ENDPOINTS[endpoint]
        response = kernel_source("sk_test", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        # Partitioning is left to the pipeline's auto-detection for this alpha release.
        assert response.partition_mode is None
        assert response.partition_keys is None
