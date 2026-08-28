import json
import dataclasses
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

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

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the lever module.
LEVER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.lever.lever.make_tracked_session"
)


def _make_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(items: list[dict[str, Any]], has_next: bool, next_offset: str | None = None) -> Response:
    body: dict[str, Any] = {"data": items, "hasNext": has_next}
    if next_offset is not None:
        body["next"] = next_offset
    return _make_response(body)


def _make_manager(resume_state: LeverResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session, returning a list that captures each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _drive(endpoint: str, manager: mock.MagicMock, responses: list[Response], **kwargs: Any):
    """Run ``lever_source`` against a mocked session and return (param snapshots, yielded batches)."""
    with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        params = _wire(session, responses)
        source_response = lever_source(
            "key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs
        )
        yielded = list(cast("Iterable[Any]", source_response.items()))
    return params, yielded


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
    @mock.patch(LEVER_SESSION_PATCH)
    def test_status_code_mapping(self, mock_session_factory, status_code: int, expected_valid: bool) -> None:
        mock_session = mock_session_factory.return_value
        mock_session.get.return_value = _make_response({}, status_code=status_code)

        is_valid, error = validate_credentials("test_key")

        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    @mock.patch(LEVER_SESSION_PATCH)
    def test_bad_key_message_distinct_from_unexpected_status(self, mock_session_factory) -> None:
        mock_session = mock_session_factory.return_value

        mock_session.get.return_value = _make_response({}, status_code=401)
        _, unauthorized_error = validate_credentials("test_key")

        mock_session.get.return_value = _make_response({}, status_code=500)
        _, unexpected_error = validate_credentials("test_key")

        assert unauthorized_error == "Invalid Lever API key. Please check your key and try again."
        assert "500" in (unexpected_error or "")

    @mock.patch(LEVER_SESSION_PATCH)
    def test_network_error_is_not_valid(self, mock_session_factory) -> None:
        mock_session = mock_session_factory.return_value
        mock_session.get.side_effect = Exception("boom")

        is_valid, error = validate_credentials("test_key")

        assert is_valid is False
        assert error is not None


class TestLeverSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_primary_keys_match_settings(self, endpoint: str) -> None:
        response = lever_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.primary_keys == LEVER_ENDPOINTS[endpoint].primary_keys

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_partitioning_only_when_partition_key_present(self, endpoint: str) -> None:
        response = lever_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())
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
        response = lever_source("key", "opportunities", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.sort_mode == "asc"


class TestLeverPaginationAndResume:
    """Drive ``lever_source`` with a mocked HTTP session at the rest_client boundary."""

    def test_fresh_run_paginates_and_normalizes(self) -> None:
        manager = _make_manager()

        responses = [
            _page([{"id": "o1", "createdAt": 1700000000000}], True, "offset_2"),
            _page([{"id": "o2", "createdAt": 1700000005000}], False),
        ]

        sent_params, yielded = _drive("opportunities", manager, responses)

        # First request has no offset; second request uses the saved offset token.
        assert sent_params[0].get("offset") is None
        assert sent_params[1].get("offset") == "offset_2"
        # `limit` rides in the query params on every request.
        assert sent_params[0]["limit"] == 100

        # Timestamps were converted ms -> seconds in the yielded rows.
        flat = [row for batch in yielded for row in batch]
        assert flat == [
            {"id": "o1", "createdAt": 1700000000},
            {"id": "o2", "createdAt": 1700000005},
        ]

    def test_saves_offset_after_each_non_terminal_page(self) -> None:
        manager = _make_manager()

        responses = [
            _page([{"id": "o1"}], True, "offset_2"),
            _page([{"id": "o2"}], True, "offset_3"),
            _page([{"id": "o3"}], False),
        ]
        _drive("opportunities", manager, responses)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [LeverResumeConfig(offset="offset_2"), LeverResumeConfig(offset="offset_3")]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = _make_manager()

        responses = [_page([{"id": "only"}], False)]
        _drive("opportunities", manager, responses)

        manager.save_state.assert_not_called()

    def test_resume_seeds_first_request_with_saved_offset(self) -> None:
        manager = _make_manager(LeverResumeConfig(offset="saved_offset"))

        responses = [_page([{"id": "o5"}], False)]
        sent_params, _ = _drive("opportunities", manager, responses)

        assert sent_params[0].get("offset") == "saved_offset"

    def test_incremental_filter_param_sent_to_api(self) -> None:
        manager = _make_manager()

        responses = [_page([{"id": "o1"}], False)]
        sent_params, _ = _drive(
            "opportunities",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
            incremental_field="updatedAt",
        )

        # Watermark seconds are converted to Lever's millisecond filter param.
        assert sent_params[0]["updated_at_start"] == 1700000000000

    def test_hasnext_without_next_token_raises(self) -> None:
        manager = _make_manager()

        # hasNext is True but no `next` token -> fail loudly rather than silently
        # truncating the sync with partial data.
        responses = [_page([{"id": "o1"}], True)]
        with pytest.raises(Exception, match="hasNext was true but no next offset token"):
            _drive("opportunities", manager, responses)

        manager.save_state.assert_not_called()


class TestResumeConfigSerialization:
    def test_round_trip(self) -> None:
        cfg = LeverResumeConfig(offset="abc123")
        reconstituted = LeverResumeConfig(**json.loads(json.dumps(dataclasses.asdict(cfg))))
        assert reconstituted == cfg
