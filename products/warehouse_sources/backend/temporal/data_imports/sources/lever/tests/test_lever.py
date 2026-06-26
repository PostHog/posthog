import json
import dataclasses
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.lever.lever import (
    LEVER_ENDPOINTS,
    LeverResumeConfig,
    _build_initial_params,
    _normalize_item,
    lever_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lever.settings import ENDPOINTS


def _make_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(items: list[dict[str, Any]], has_next: bool, next_offset: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"data": items, "hasNext": has_next}
    if next_offset is not None:
        body["next"] = next_offset
    return body


class TestNormalizeItem:
    @pytest.mark.parametrize(
        "item, expected",
        [
            ({"id": "a", "createdAt": 1700000000000}, {"id": "a", "createdAt": 1700000000}),
            (
                {"id": "a", "createdAt": 1700000000000, "updatedAt": 1700000005000},
                {"id": "a", "createdAt": 1700000000, "updatedAt": 1700000005},
            ),
            ({"id": "a"}, {"id": "a"}),  # no timestamp fields -> untouched
            ({"id": "a", "createdAt": None}, {"id": "a", "createdAt": None}),  # null preserved
        ],
    )
    def test_milliseconds_converted_to_seconds(self, item: dict[str, Any], expected: dict[str, Any]) -> None:
        assert _normalize_item(item) == expected


class TestBuildInitialParams:
    def test_full_refresh_only_sets_limit(self) -> None:
        params = _build_initial_params(LEVER_ENDPOINTS["users"], False, None, None)
        assert params == {"limit": 100}

    def test_first_incremental_sync_has_no_filter(self) -> None:
        # No watermark yet (initial sync) -> pull everything, only limit is set.
        params = _build_initial_params(LEVER_ENDPOINTS["opportunities"], True, None, "updatedAt")
        assert params == {"limit": 100}

    def test_incremental_filter_converts_seconds_to_milliseconds(self) -> None:
        params = _build_initial_params(LEVER_ENDPOINTS["opportunities"], True, 1700000000, "updatedAt")
        assert params == {"limit": 100, "updated_at_start": 1700000000000}

    def test_incremental_filter_uses_chosen_cursor_field(self) -> None:
        params = _build_initial_params(LEVER_ENDPOINTS["opportunities"], True, 1700000000, "createdAt")
        assert params == {"limit": 100, "created_at_start": 1700000000000}

    def test_unknown_cursor_field_is_ignored(self) -> None:
        params = _build_initial_params(LEVER_ENDPOINTS["opportunities"], True, 1700000000, "somethingElse")
        assert params == {"limit": 100}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.lever.lever.make_tracked_session")
    def test_status_code_mapping(self, mock_session_factory, status_code: int, expected_valid: bool) -> None:
        mock_session = mock_session_factory.return_value
        mock_session.get.return_value = _make_response({}, status_code=status_code)

        is_valid, error = validate_credentials("test_key")

        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.lever.lever.make_tracked_session")
    def test_network_error_is_not_valid(self, mock_session_factory) -> None:
        mock_session = mock_session_factory.return_value
        mock_session.get.side_effect = Exception("boom")

        is_valid, error = validate_credentials("test_key")

        assert is_valid is False
        assert error == "boom"


class TestLeverSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_primary_keys_match_settings(self, endpoint: str) -> None:
        response = lever_source("key", endpoint, MagicMock(), MagicMock())
        assert response.primary_keys == LEVER_ENDPOINTS[endpoint].primary_keys

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_partitioning_only_when_partition_key_present(self, endpoint: str) -> None:
        response = lever_source("key", endpoint, MagicMock(), MagicMock())
        partition_key = LEVER_ENDPOINTS[endpoint].partition_key

        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_partition_key_is_never_updated_at(self) -> None:
        for endpoint in ENDPOINTS:
            assert LEVER_ENDPOINTS[endpoint].partition_key != "updatedAt"

    def test_sort_mode_is_ascending(self) -> None:
        response = lever_source("key", "opportunities", MagicMock(), MagicMock())
        assert response.sort_mode == "asc"


class TestLeverPaginationAndResume:
    """Drive ``get_rows`` (via ``lever_source``) with a mocked HTTP session."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[list[dict[str, Any]], list[Any]]:
        """Returns (params sent per request, batches yielded by the source)."""
        sent_params: list[dict[str, Any]] = []
        yielded: list[Any] = []
        response_iter = iter(responses)

        def fake_get(url: str, *_args: Any, **kwargs: Any) -> Response:
            sent_params.append(dict(kwargs.get("params", {})))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.lever.lever.make_tracked_session"
        ) as mock_factory:
            mock_factory.return_value.get.side_effect = fake_get

            response = lever_source("key", endpoint, MagicMock(), manager)
            yielded.extend(cast(Iterable[Any], response.items()))

        return sent_params, yielded

    def test_fresh_run_paginates_and_normalizes(self) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = False

        responses = [
            _make_response(_page([{"id": "o1", "createdAt": 1700000000000}], True, "offset_2")),
            _make_response(_page([{"id": "o2", "createdAt": 1700000005000}], False)),
        ]

        sent_params, yielded = self._drive("opportunities", manager, responses)

        # First request has no offset; second request uses the saved offset token.
        assert sent_params[0].get("offset") is None
        assert sent_params[1].get("offset") == "offset_2"

        # Timestamps were converted ms -> seconds in the yielded rows.
        flat = [row for batch in yielded for row in batch]
        assert flat == [
            {"id": "o1", "createdAt": 1700000000},
            {"id": "o2", "createdAt": 1700000005},
        ]

    def test_saves_offset_after_each_non_terminal_page(self) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = False

        responses = [
            _make_response(_page([{"id": "o1"}], True, "offset_2")),
            _make_response(_page([{"id": "o2"}], True, "offset_3")),
            _make_response(_page([{"id": "o3"}], False)),
        ]
        self._drive("opportunities", manager, responses)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [LeverResumeConfig(offset="offset_2"), LeverResumeConfig(offset="offset_3")]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = False

        responses = [_make_response(_page([{"id": "only"}], False))]
        self._drive("opportunities", manager, responses)

        manager.save_state.assert_not_called()

    def test_resume_seeds_first_request_with_saved_offset(self) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = LeverResumeConfig(offset="saved_offset")

        responses = [_make_response(_page([{"id": "o5"}], False))]
        sent_params, _ = self._drive("opportunities", manager, responses)

        assert sent_params[0].get("offset") == "saved_offset"

    def test_hasnext_without_next_token_raises(self) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = False

        # hasNext is True but no `next` token -> fail loudly rather than silently
        # truncating the sync with partial data.
        responses = [_make_response(_page([{"id": "o1"}], True))]
        with pytest.raises(Exception, match="hasNext was true but no next offset token"):
            self._drive("opportunities", manager, responses)

        manager.save_state.assert_not_called()


class TestResumeConfigSerialization:
    def test_round_trip(self) -> None:
        cfg = LeverResumeConfig(offset="abc123")
        reconstituted = LeverResumeConfig(**json.loads(json.dumps(dataclasses.asdict(cfg))))
        assert reconstituted == cfg
