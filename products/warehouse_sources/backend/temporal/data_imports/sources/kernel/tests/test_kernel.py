from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.kernel.kernel import (
    PAGE_SIZE,
    KernelResumeConfig,
    KernelRetryableError,
    _extract_items,
    _next_page,
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


class _FakeResumableManager:
    def __init__(self, state: KernelResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[KernelResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> KernelResumeConfig | None:
        return self._state

    def save_state(self, data: KernelResumeConfig) -> None:
        self.saved.append(data)


class TestExtractItems:
    @pytest.mark.parametrize(
        "body, expected",
        [
            ([{"id": "a"}], [{"id": "a"}]),
            ({"data": [{"id": "b"}]}, [{"id": "b"}]),
            ({"items": [{"id": "c"}]}, [{"id": "c"}]),
            ({"results": [{"id": "d"}]}, [{"id": "d"}]),
            ({"unexpected": [{"id": "e"}]}, []),
            ({}, []),
            (None, []),
        ],
    )
    def test_extract_items_handles_shapes(self, body: Any, expected: list[dict]) -> None:
        assert _extract_items(body) == expected


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

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_transport_failure_returns_none_status(self, mock_session: Any) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("sk_test") == (False, None)


class TestGetRows:
    def _collect(self, endpoint: str, manager: _FakeResumableManager) -> list[dict]:
        rows: list[dict] = []
        for table in get_rows("sk_test", endpoint, mock.MagicMock(), manager):  # type: ignore[arg-type]
            rows.extend(table.to_pylist())
        return rows

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_single_page_full_refresh(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = _response([{"id": "a1"}, {"id": "a2"}], has_more=False)

        rows = self._collect("apps", _FakeResumableManager())

        assert rows == [{"id": "a1"}, {"id": "a2"}]
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_offset_pagination_follows_next_offset_header(self, mock_session: Any) -> None:
        mock_session.return_value.get.side_effect = [
            _response([{"id": "a1"}], has_more=True, next_offset=100),
            _response([{"id": "a2"}], has_more=False),
        ]

        rows = self._collect("deployments", _FakeResumableManager())

        assert rows == [{"id": "a1"}, {"id": "a2"}]
        urls = [call.kwargs.get("url") or call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert "offset=0" in urls[0]
        assert "offset=100" in urls[1]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_first_page_yields_nothing(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = _response([], has_more=False)
        assert self._collect("profiles", _FakeResumableManager()) == []

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_browsers_requests_all_statuses(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = _response([{"id": "b1"}], has_more=False)

        self._collect("browsers", _FakeResumableManager())

        url = mock_session.return_value.get.call_args.args[0]
        assert "status=all" in url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resume_starts_from_saved_offset(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = _response([{"id": "a1"}], has_more=False)

        self._collect("apps", _FakeResumableManager(KernelResumeConfig(offset=250)))

        url = mock_session.return_value.get.call_args.args[0]
        assert "offset=250" in url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_saves_state_after_yielding_a_batch(self, mock_session: Any) -> None:
        # A batch flushes at 2000 rows; 20 full pages of 100 trigger one yield with more pages left,
        # so the manager must persist the next offset to resume from.
        pages = [
            _response(
                [{"id": f"p{page}-{i}"} for i in range(PAGE_SIZE)], has_more=True, next_offset=(page + 1) * PAGE_SIZE
            )
            for page in range(20)
        ]
        pages.append(_response([{"id": "last"}], has_more=False))
        mock_session.return_value.get.side_effect = pages

        manager = _FakeResumableManager()
        self._collect("invocations", manager)

        assert manager.saved == [KernelResumeConfig(offset=2000)]

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retries_retryable_status_then_succeeds(self, mock_session: Any, _sleep: Any) -> None:
        mock_session.return_value.get.side_effect = [
            _response(None, status_code=500),
            _response(None, status_code=429),
            _response([{"id": "a1"}], has_more=False),
        ]

        rows = self._collect("apps", _FakeResumableManager())

        assert rows == [{"id": "a1"}]
        assert mock_session.return_value.get.call_count == 3

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retries_exhausted_raises(self, mock_session: Any, _sleep: Any) -> None:
        mock_session.return_value.get.return_value = _response(None, status_code=503)

        with pytest.raises(KernelRetryableError):
            self._collect("apps", _FakeResumableManager())

        assert mock_session.return_value.get.call_count == 5


class TestKernelSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = KERNEL_ENDPOINTS[endpoint]
        response = kernel_source("sk_test", endpoint, mock.MagicMock(), mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        # Partitioning is left to the pipeline's auto-detection for this alpha release.
        assert response.partition_mode is None
        assert response.partition_keys is None
