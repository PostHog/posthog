import dataclasses
from datetime import UTC, date, datetime
from typing import Any, cast

from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.trello.settings import TRELLO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello import (
    TrelloResumeConfig,
    _add_created_at,
    _format_incremental_value,
    _get_headers,
    _id_to_created_at,
    get_rows,
    trello_source,
    validate_credentials,
)


def _make_response(status: int = 200, body: Any = None) -> mock.Mock:
    resp = mock.Mock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body if body is not None else []
    resp.text = ""
    return resp


def _make_manager(*, can_resume: bool = False, resume_state: TrelloResumeConfig | None = None) -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = resume_state
    manager.save_state = mock.Mock()
    return manager


class _ImmediateBatcher:
    """Test double for Batcher that emits every batched item as its own chunk."""

    def __init__(self) -> None:
        self._item: Any = None

    def batch(self, item: Any) -> None:
        self._item = item

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        return self._item is not None

    def get_table(self) -> Any:
        item = self._item
        self._item = None
        return item


def _patch_batcher() -> Any:
    return mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello.Batcher",
        autospec=False,
        side_effect=lambda logger, chunk_size, chunk_size_bytes: _ImmediateBatcher(),
    )


def _run(endpoint: str, manager: mock.Mock, get_mock: mock.Mock, **kwargs: Any) -> list[Any]:
    return list(
        get_rows(
            api_key="key",
            api_token="token",
            endpoint=endpoint,
            logger=mock.Mock(),
            resumable_source_manager=manager,
            **kwargs,
        )
    )


class TestIdToCreatedAt:
    @parameterized.expand(
        [
            # 0x5abbe394 = 1522242964 = 2018-03-28T18:48:52+00:00
            ("valid_object_id", "5abbe394c78f17ffa9e10843", "2018-03-28T18:48:52+00:00"),
            ("too_short", "abc", None),
            ("non_hex_prefix", "zzzzzzzzc78f17ffa9e10843", None),
            ("not_a_string", 12345, None),
            ("none", None, None),
        ]
    )
    def test_id_to_created_at(self, _name: str, obj_id: Any, expected: str | None) -> None:
        assert _id_to_created_at(obj_id) == expected


class TestAddCreatedAt:
    def test_injects_created_at_from_id(self) -> None:
        item = _add_created_at({"id": "5abbe394c78f17ffa9e10843", "name": "Board"})
        assert item["created_at"] == "2018-03-28T18:48:52+00:00"

    def test_preserves_existing_created_at(self) -> None:
        item = _add_created_at({"id": "5abbe394c78f17ffa9e10843", "created_at": "already"})
        assert item["created_at"] == "already"

    def test_no_id_leaves_item_unchanged(self) -> None:
        item = _add_created_at({"name": "no id"})
        assert "created_at" not in item


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC), "2026-01-15T10:00:00+00:00"),
            ("naive_datetime", datetime(2026, 1, 15, 10, 0, 0), "2026-01-15T10:00:00+00:00"),
            ("date", date(2026, 1, 15), "2026-01-15T00:00:00+00:00"),
            ("string_passthrough", "2026-01-15T10:00:00Z", "2026-01-15T10:00:00Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestGetHeaders:
    def test_oauth_header_keeps_token_out_of_url(self) -> None:
        headers = _get_headers("my-key", "my-token")
        assert headers["Authorization"] == 'OAuth oauth_consumer_key="my-key", oauth_token="my-token"'


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("missing_token", 400, False, "Invalid Trello API key or token"),
            ("invalid_key", 401, False, "Invalid Trello API key or token"),
            ("forbidden", 403, False, "Your Trello token does not have the required permissions"),
        ]
    )
    def test_status_codes(self, _name: str, status: int, valid: bool, message: str | None) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello.make_tracked_session"
        ) as session:
            session.return_value.get.return_value = mock.MagicMock(status_code=status)
            result_valid, result_message = validate_credentials("key", "token")

        assert result_valid is valid
        assert result_message == message

    def test_request_exception(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello.make_tracked_session"
        ) as session:
            session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
            valid, message = validate_credentials("key", "token")

        assert valid is False
        assert message is not None
        assert "boom" in message

    def test_sends_oauth_header(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello.make_tracked_session"
        ) as session:
            session.return_value.get.return_value = mock.MagicMock(status_code=200)
            validate_credentials("my-key", "my-token")

        headers = session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == 'OAuth oauth_consumer_key="my-key", oauth_token="my-token"'


class TestMemberEndpoint:
    def test_boards_single_request_injects_created_at(self) -> None:
        manager = _make_manager()
        boards = [{"id": "5abbe394c78f17ffa9e10843", "name": "A"}, {"id": "5abbe395c78f17ffa9e10843", "name": "B"}]

        with (
            _patch_batcher(),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello.make_tracked_session"
            ) as session,
        ):
            session.return_value.get.side_effect = [_make_response(body=boards)]
            rows = _run("boards", manager, session, should_use_incremental_field=False)

        assert [r["name"] for r in rows] == ["A", "B"]
        assert all("created_at" in r for r in rows)
        # Member endpoints are a single request; no resume checkpoints.
        manager.save_state.assert_not_called()
        url = session.return_value.get.call_args_list[0].args[0]
        assert url.startswith("https://api.trello.com/1/members/me/boards")

    def test_non_list_body_yields_nothing(self) -> None:
        manager = _make_manager()
        with (
            _patch_batcher(),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello.make_tracked_session"
            ) as session,
        ):
            session.return_value.get.side_effect = [_make_response(body={"error": "nope"})]
            rows = _run("organizations", manager, session)

        assert rows == []


class TestBoardFanOut:
    def test_lists_fan_out_across_boards(self) -> None:
        manager = _make_manager()
        board_ids = [{"id": "board1"}, {"id": "board2"}]
        lists_b1 = [{"id": "l1"}]
        lists_b2 = [{"id": "l2"}, {"id": "l3"}]

        with (
            _patch_batcher(),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello.make_tracked_session"
            ) as session,
        ):
            session.return_value.get.side_effect = [
                _make_response(body=board_ids),
                _make_response(body=lists_b1),
                _make_response(body=lists_b2),
            ]
            rows = _run("lists", manager, session)

        assert [r["id"] for r in rows] == ["l1", "l2", "l3"]
        urls = [c.args[0] for c in session.return_value.get.call_args_list]
        assert "/members/me/boards?fields=id" in urls[0]
        assert "/boards/board1/lists" in urls[1]
        assert "/boards/board2/lists" in urls[2]
        # Each completed board advances the resume index.
        saved_indices = [c.args[0].board_index for c in manager.save_state.call_args_list]
        assert saved_indices[-1] == 2

    def test_resume_skips_completed_boards(self) -> None:
        manager = _make_manager(can_resume=True, resume_state=TrelloResumeConfig(board_index=1, before_cursor=None))
        board_ids = [{"id": "board1"}, {"id": "board2"}]

        with (
            _patch_batcher(),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello.make_tracked_session"
            ) as session,
        ):
            session.return_value.get.side_effect = [
                _make_response(body=board_ids),
                _make_response(body=[{"id": "l2"}]),
            ]
            rows = _run("lists", manager, session)

        # Only board2 (index 1) is synced; board1 is skipped.
        assert [r["id"] for r in rows] == ["l2"]
        urls = [c.args[0] for c in session.return_value.get.call_args_list]
        assert not any("/boards/board1/" in u for u in urls)
        assert any("/boards/board2/lists" in u for u in urls)


class TestActionsIncremental:
    def test_incremental_sends_since_and_limit(self) -> None:
        manager = _make_manager()
        cutoff = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)

        with (
            _patch_batcher(),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello.make_tracked_session"
            ) as session,
        ):
            session.return_value.get.side_effect = [
                _make_response(body=[{"id": "b1"}]),
                _make_response(body=[{"id": "a1", "date": "2026-02-01T00:00:00Z"}]),
            ]
            _run(
                "actions",
                manager,
                session,
                should_use_incremental_field=True,
                db_incremental_field_last_value=cutoff,
            )

        actions_url = session.return_value.get.call_args_list[1].args[0]
        assert "since=2026-01-15T10" in actions_url
        assert "limit=1000" in actions_url

    def test_full_refresh_omits_since(self) -> None:
        manager = _make_manager()
        with (
            _patch_batcher(),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello.make_tracked_session"
            ) as session,
        ):
            session.return_value.get.side_effect = [
                _make_response(body=[{"id": "b1"}]),
                _make_response(body=[{"id": "a1"}]),
            ]
            _run("actions", manager, session, should_use_incremental_field=False)

        actions_url = session.return_value.get.call_args_list[1].args[0]
        assert "since=" not in actions_url

    def test_paginates_with_before_cursor(self) -> None:
        # Drive pagination directly with a small page size so we don't need 1000 rows.
        manager = _make_manager()
        config = dataclasses.replace(TRELLO_ENDPOINTS["actions"], page_size=2)

        from products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello import _sync_board_actions

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello.make_tracked_session"
            ) as session,
        ):
            session.return_value.get.side_effect = [
                _make_response(body=[{"id": "a1"}, {"id": "a2"}]),  # full page → keep paging
                _make_response(body=[{"id": "a3"}]),  # short page → stop
            ]
            batcher = _ImmediateBatcher()
            rows = list(
                _sync_board_actions(
                    board_id="b1",
                    index=0,
                    config=config,
                    headers={},
                    logger=mock.Mock(),
                    batcher=cast(Batcher, batcher),
                    manager=manager,
                    since=None,
                    before=None,
                )
            )

        assert [r["id"] for r in rows] == ["a1", "a2", "a3"]
        urls = [c.args[0] for c in session.return_value.get.call_args_list]
        assert "before=" not in urls[0]
        assert "before=a2" in urls[1]
        # Board fully drained → resume index advances past this board.
        assert manager.save_state.call_args_list[-1].args[0].board_index == 1

    def test_resume_uses_before_cursor(self) -> None:
        manager = _make_manager(can_resume=True, resume_state=TrelloResumeConfig(board_index=0, before_cursor="oldest"))
        with (
            _patch_batcher(),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello.make_tracked_session"
            ) as session,
        ):
            session.return_value.get.side_effect = [
                _make_response(body=[{"id": "b1"}]),
                _make_response(body=[{"id": "a1"}]),
            ]
            _run("actions", manager, session, should_use_incremental_field=False)

        actions_url = session.return_value.get.call_args_list[1].args[0]
        assert "before=oldest" in actions_url


class TestTrelloSourceResponse:
    @parameterized.expand(
        [
            ("boards", "asc", "id"),
            ("actions", "desc", "id"),
            ("cards", "asc", "id"),
        ]
    )
    def test_source_response_shape(self, endpoint: str, sort_mode: str, primary_key: str) -> None:
        response = trello_source(
            api_key="key",
            api_token="token",
            endpoint=endpoint,
            logger=mock.Mock(),
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.sort_mode == sort_mode
        assert response.primary_keys == [primary_key]
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"

    @parameterized.expand([(name,) for name in TRELLO_ENDPOINTS])
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        response = trello_source(
            api_key="key",
            api_token="token",
            endpoint=endpoint,
            logger=mock.Mock(),
            resumable_source_manager=_make_manager(),
        )
        assert callable(response.items)
        assert response.primary_keys == [TRELLO_ENDPOINTS[endpoint].primary_key]


class TestRetryClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise(self, _name: str, status: int) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello import (
            TrelloRetryableError,
            _fetch,
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello.make_tracked_session"
        ) as session:
            session.return_value.get.return_value = _make_response(status=status)
            # __wrapped__ skips tenacity so we assert the single-attempt classification.
            try:
                _fetch.__wrapped__("https://api.trello.com/1/members/me", {}, mock.Mock())  # type: ignore[attr-defined]
            except TrelloRetryableError:
                return
            raise AssertionError("expected TrelloRetryableError")
