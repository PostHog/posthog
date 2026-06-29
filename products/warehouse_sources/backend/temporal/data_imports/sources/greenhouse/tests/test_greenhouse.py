import json
import dataclasses
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.greenhouse import (
    GREENHOUSE_ENDPOINTS,
    PAGE_SIZE,
    GreenhouseResumeConfig,
    _build_initial_params,
    _format_datetime,
    greenhouse_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.settings import ENDPOINTS


def _make_response(body: Any, status_code: int = 200, next_url: str | None = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    if next_url is not None:
        # RFC 5988 Link header, as Harvest returns it. requests parses this into `resp.links`.
        resp.headers["Link"] = f'<{next_url}>; rel="next"'
    return resp


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),  # naive -> treated as UTC
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format_datetime(self, value: object, expected: str) -> None:
        assert _format_datetime(value) == expected

    def test_no_plus_zero_offset(self) -> None:
        assert "+00:00" not in _format_datetime(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestBuildInitialParams:
    def test_full_refresh_only_sets_per_page(self) -> None:
        params = _build_initial_params(GREENHOUSE_ENDPOINTS["departments"], False, None, None)
        assert params == {"per_page": PAGE_SIZE}

    def test_first_incremental_sync_has_no_filter(self) -> None:
        # No watermark yet -> pull everything, only per_page is set.
        params = _build_initial_params(GREENHOUSE_ENDPOINTS["candidates"], True, None, "updated_at")
        assert params == {"per_page": PAGE_SIZE}

    def test_incremental_filter_maps_updated_at_to_updated_after(self) -> None:
        watermark = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        params = _build_initial_params(GREENHOUSE_ENDPOINTS["candidates"], True, watermark, "updated_at")
        assert params == {"per_page": PAGE_SIZE, "updated_after": "2026-03-04T02:58:14.000Z"}

    def test_incremental_filter_uses_chosen_cursor_field(self) -> None:
        watermark = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        params = _build_initial_params(GREENHOUSE_ENDPOINTS["candidates"], True, watermark, "created_at")
        assert params == {"per_page": PAGE_SIZE, "created_after": "2026-03-04T02:58:14.000Z"}

    def test_applications_uses_last_activity_after(self) -> None:
        watermark = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        params = _build_initial_params(GREENHOUSE_ENDPOINTS["applications"], True, watermark, "last_activity_at")
        assert params == {"per_page": PAGE_SIZE, "last_activity_after": "2026-03-04T02:58:14.000Z"}

    def test_unknown_cursor_field_is_ignored(self) -> None:
        watermark = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        params = _build_initial_params(GREENHOUSE_ENDPOINTS["candidates"], True, watermark, "somethingElse")
        assert params == {"per_page": PAGE_SIZE}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, accept_forbidden, expected_valid",
        [
            (200, True, True),
            (200, False, True),
            (401, True, False),
            (401, False, False),
            (403, True, True),  # source-create: a scoped key may legitimately 403
            (403, False, False),  # per-schema check: missing scope is an error
            (500, True, False),
        ],
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.greenhouse.make_tracked_session"
    )
    def test_status_code_mapping(
        self, mock_session_factory: MagicMock, status_code: int, accept_forbidden: bool, expected_valid: bool
    ) -> None:
        mock_session = mock_session_factory.return_value
        mock_session.get.return_value = _make_response({}, status_code=status_code)

        is_valid, error = validate_credentials("test_key", accept_forbidden=accept_forbidden)

        assert is_valid is expected_valid
        assert (error is None) is expected_valid

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.greenhouse.make_tracked_session"
    )
    def test_network_error_is_not_valid(self, mock_session_factory: MagicMock) -> None:
        mock_session_factory.return_value.get.side_effect = Exception("boom")
        is_valid, error = validate_credentials("test_key")
        assert is_valid is False
        assert error == "boom"


class TestGreenhouseSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_primary_keys_match_settings(self, endpoint: str) -> None:
        response = greenhouse_source("key", endpoint, MagicMock(), MagicMock())
        assert response.primary_keys == GREENHOUSE_ENDPOINTS[endpoint].primary_keys

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_partitioning_only_when_partition_key_present(self, endpoint: str) -> None:
        response = greenhouse_source("key", endpoint, MagicMock(), MagicMock())
        partition_key = GREENHOUSE_ENDPOINTS[endpoint].partition_key

        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_partition_key_is_never_updated_at(self, endpoint: str) -> None:
        assert GREENHOUSE_ENDPOINTS[endpoint].partition_key not in ("updated_at", "last_activity_at")

    def test_sort_mode_is_ascending(self) -> None:
        assert greenhouse_source("key", "candidates", MagicMock(), MagicMock()).sort_mode == "asc"


class TestGreenhousePaginationAndResume:
    """Drive ``get_rows`` (via ``greenhouse_source``) with a mocked HTTP session."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[list[tuple[str, dict[str, Any] | None]], list[Any]]:
        """Returns (per-request (url, params) tuples, batches yielded by the source)."""
        sent: list[tuple[str, dict[str, Any] | None]] = []
        yielded: list[Any] = []
        response_iter = iter(responses)

        def fake_get(url: str, *_args: Any, **kwargs: Any) -> Response:
            sent.append((url, kwargs.get("params")))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.greenhouse.make_tracked_session"
        ) as mock_factory:
            mock_factory.return_value.get.side_effect = fake_get

            response = greenhouse_source("key", endpoint, MagicMock(), manager)
            yielded.extend(cast(Iterable[Any], response.items()))

        return sent, yielded

    def test_fresh_run_follows_link_header(self) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = False

        next_url = "https://harvest.greenhouse.io/v1/candidates?per_page=500&page=2"
        responses = [
            _make_response([{"id": 1}], next_url=next_url),
            _make_response([{"id": 2}]),  # no Link header -> last page
        ]

        sent, yielded = self._drive("candidates", manager, responses)

        # First request hits the path with params; second follows the Link URL verbatim (no params).
        assert sent[0][0] == "https://harvest.greenhouse.io/v1/candidates"
        assert sent[0][1] == {"per_page": PAGE_SIZE}
        assert sent[1] == (next_url, None)

        flat = [row for batch in yielded for row in batch]
        assert flat == [{"id": 1}, {"id": 2}]

    def test_saves_next_url_after_each_non_terminal_page(self) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = False

        url2 = "https://harvest.greenhouse.io/v1/jobs?per_page=500&page=2"
        url3 = "https://harvest.greenhouse.io/v1/jobs?per_page=500&page=3"
        responses = [
            _make_response([{"id": 1}], next_url=url2),
            _make_response([{"id": 2}], next_url=url3),
            _make_response([{"id": 3}]),
        ]
        self._drive("jobs", manager, responses)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [GreenhouseResumeConfig(next_url=url2), GreenhouseResumeConfig(next_url=url3)]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = False

        self._drive("jobs", manager, [_make_response([{"id": 1}])])
        manager.save_state.assert_not_called()

    def test_resume_seeds_first_request_with_saved_next_url(self) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = True
        saved_url = "https://harvest.greenhouse.io/v1/candidates?per_page=500&page=5"
        manager.load_state.return_value = GreenhouseResumeConfig(next_url=saved_url)

        sent, _ = self._drive("candidates", manager, [_make_response([{"id": 9}])])

        assert sent[0] == (saved_url, None)

    def test_empty_page_yields_nothing_and_stops(self) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = False

        sent, yielded = self._drive("jobs", manager, [_make_response([])])
        assert yielded == []
        assert len(sent) == 1


class TestResumeConfigSerialization:
    def test_round_trip(self) -> None:
        cfg = GreenhouseResumeConfig(next_url="https://harvest.greenhouse.io/v1/candidates?page=3")
        reconstituted = GreenhouseResumeConfig(**json.loads(json.dumps(dataclasses.asdict(cfg))))
        assert reconstituted == cfg
