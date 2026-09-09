import json
from datetime import UTC, date, datetime
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.decagon import (
    DECAGON_BASE_URL,
    DecagonResumeConfig,
    _to_epoch_seconds,
    decagon_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.settings import (
    DECAGON_ENDPOINTS,
    DecagonEndpointConfig,
)

DECAGON_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.decagon.decagon"
SETTINGS_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.decagon.settings"


def _make_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _conversation(conversation_id: str) -> dict[str, Any]:
    return {"conversation_id": conversation_id, "created_at": "2026-01-01T00:00:00Z"}


def _drive_rows(
    manager: MagicMock, responses: list[Response], endpoint: str = "conversations", **incremental_kwargs: Any
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
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
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,
                **incremental_kwargs,
            )
        )
    return sent_params, batches


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
    def _drive(
        self, manager: MagicMock, responses: list[Response], **incremental_kwargs: Any
    ) -> tuple[list[dict[str, Any]], list[list[str]]]:
        sent_params, batches = _drive_rows(manager, responses, **incremental_kwargs)
        yielded_ids = [[item["conversation_id"] for item in batch] for batch in batches]
        return sent_params, yielded_ids

    def _fresh_manager(self) -> MagicMock:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        return manager

    # Decagon's docs name the next-page field three different ways (reference prose,
    # example code, example response); the connector must paginate with whichever one
    # the API returns, else a full refresh silently truncates to the first 100 rows.
    @parameterized.expand(
        [
            ("prose_name", "next_page_cursor", "cur-1", "cur-2"),
            ("example_code_name", "next_cursor", "cur-1", "cur-2"),
            ("example_response_name_int_watermark", "next_page_updated_after", 1704067200, 1704153600),
        ]
    )
    def test_paginates_with_each_documented_cursor_key_and_saves_state_after_each_yield(
        self, _name: str, cursor_key: str, cursor_1: Any, cursor_2: Any
    ) -> None:
        manager = self._fresh_manager()
        responses = [
            _make_response({"conversations": [_conversation("c1")], cursor_key: cursor_1}),
            _make_response({"conversations": [_conversation("c2")], cursor_key: cursor_2}),
            _make_response({"conversations": [_conversation("c3")], cursor_key: None}),
        ]
        sent_params, yielded_ids = self._drive(manager, responses)

        # First request omits the cursor (starts at the oldest conversations).
        assert sent_params == [{}, {"cursor": str(cursor_1)}, {"cursor": str(cursor_2)}]
        assert yielded_ids == [["c1"], ["c2"], ["c3"]]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [DecagonResumeConfig(cursor=str(cursor_1)), DecagonResumeConfig(cursor=str(cursor_2))]
        # A retried attempt of this completed job must start fresh, not resume at the
        # final page and append its rows again.
        manager.clear_state.assert_called_once()

    def test_null_prose_cursor_key_does_not_mask_a_populated_alias(self) -> None:
        manager = self._fresh_manager()
        responses = [
            _make_response({"conversations": [_conversation("c1")], "next_page_cursor": None, "next_cursor": "cur-1"}),
            _make_response({"conversations": [_conversation("c2")], "next_page_cursor": None, "next_cursor": None}),
        ]
        sent_params, yielded_ids = self._drive(manager, responses)

        assert sent_params == [{}, {"cursor": "cur-1"}]
        assert yielded_ids == [["c1"], ["c2"]]

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

    def test_incremental_walk_sends_window_on_every_page_and_saves_it(self) -> None:
        manager = self._fresh_manager()
        watermark = datetime(2026, 1, 15, 12, 0, 5, tzinfo=UTC)
        epoch = str(int(watermark.timestamp()))
        responses = [
            _make_response({"conversations": [_conversation("c1")], "next_page_cursor": "cur-1"}),
            _make_response({"conversations": [_conversation("c2")], "next_page_cursor": None}),
        ]
        sent_params, yielded_ids = self._drive(
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
            incremental_field="updated_at",
        )

        assert sent_params == [
            {"min_timestamp": epoch, "timestamp_filter": "updated_at"},
            {"cursor": "cur-1", "min_timestamp": epoch, "timestamp_filter": "updated_at"},
        ]
        assert yielded_ids == [["c1"], ["c2"]]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [DecagonResumeConfig(cursor="cur-1", min_timestamp=int(epoch), timestamp_filter="updated_at")]

    def test_first_incremental_sync_without_watermark_walks_the_full_export(self) -> None:
        manager = self._fresh_manager()
        responses = [_make_response({"conversations": [_conversation("c1")], "next_page_cursor": None})]
        sent_params, yielded_ids = self._drive(
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updated_at",
        )
        assert sent_params == [{}]
        assert yielded_ids == [["c1"]]

    def test_incremental_walk_reemits_reappearing_conversations_for_the_merge(self) -> None:
        # Incremental writes merge on conversation_id and keep the last occurrence, so the
        # re-emission carries the newer version. Skipping it client-side (the full-refresh
        # dedupe) would persist the stale first copy.
        manager = self._fresh_manager()
        responses = [
            _make_response({"conversations": [_conversation("c1"), _conversation("c2")], "next_page_cursor": "cur-1"}),
            _make_response({"conversations": [_conversation("c2"), _conversation("c3")], "next_page_cursor": None}),
        ]
        _, yielded_ids = self._drive(
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert yielded_ids == [["c1", "c2"], ["c2", "c3"]]

    def test_resumed_incremental_run_reuses_the_saved_window(self) -> None:
        # The stored watermark advances as batches land, so recomputing the window on resume
        # would pair a fresh min_timestamp with a cursor positioned inside the old window and
        # skip rows at the boundary.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = DecagonResumeConfig(
            cursor="cur-resumed", min_timestamp=1768478405, timestamp_filter="updated_at"
        )

        responses = [_make_response({"conversations": [_conversation("c9")], "next_page_cursor": None})]
        sent_params, _ = self._drive(
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
            incremental_field="updated_at",
        )

        assert sent_params == [
            {"cursor": "cur-resumed", "min_timestamp": "1768478405", "timestamp_filter": "updated_at"}
        ]

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


def _synthetic_endpoint(**overrides: Any) -> DecagonEndpointConfig:
    defaults: dict[str, Any] = {
        "name": "synthetic",
        "path": "/synthetic",
        "data_key": "rows",
        "primary_keys": ["id"],
        "incremental_fields": [],
        "pagination": "single",
    }
    defaults.update(overrides)
    return DecagonEndpointConfig(**defaults)


def _row(row_id: str) -> dict[str, Any]:
    return {"id": row_id}


def _fresh_manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


# The walker is config-driven, so each pagination mode is exercised through a synthetic
# endpoint config rather than waiting for a real endpoint to adopt it.
class TestPaginationModes:
    def test_single_mode_makes_exactly_one_request_with_no_pagination_params(self) -> None:
        cfg = _synthetic_endpoint(pagination="single", extra_params={"get_counts": "true"})
        with patch.dict(DECAGON_ENDPOINTS, {"synthetic": cfg}):
            manager = _fresh_manager()
            responses = [_make_response({"rows": [_row("r1"), _row("r2")]})]
            sent_params, batches = _drive_rows(manager, responses, endpoint="synthetic")
        assert sent_params == [{"get_counts": "true"}]
        assert [[r["id"] for r in b] for b in batches] == [["r1", "r2"]]
        manager.save_state.assert_not_called()

    def test_page_mode_terminates_on_total_counting_rows_actually_received(self) -> None:
        # The server may cap the requested page_size; counting received rows against the
        # total keeps termination exact instead of stopping after a "short" capped page.
        cfg = _synthetic_endpoint(pagination="page", page_size=3, total_key="total")
        with patch.dict(DECAGON_ENDPOINTS, {"synthetic": cfg}):
            manager = _fresh_manager()
            responses = [
                _make_response({"rows": [_row("r1"), _row("r2")], "total": 5}),
                _make_response({"rows": [_row("r3"), _row("r4")], "total": 5}),
                _make_response({"rows": [_row("r5")], "total": 5}),
            ]
            sent_params, batches = _drive_rows(manager, responses, endpoint="synthetic")
        assert sent_params == [
            {"page": "1", "page_size": "3"},
            {"page": "2", "page_size": "3"},
            {"page": "3", "page_size": "3"},
        ]
        assert len(batches) == 3
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            DecagonResumeConfig(page=2, rows_walked=2),
            DecagonResumeConfig(page=3, rows_walked=4),
        ]

    def test_page_mode_without_total_falls_back_to_short_page_termination(self) -> None:
        cfg = _synthetic_endpoint(pagination="page", page_size=2, total_key="total")
        with patch.dict(DECAGON_ENDPOINTS, {"synthetic": cfg}):
            manager = _fresh_manager()
            responses = [
                _make_response({"rows": [_row("r1"), _row("r2")]}),
                _make_response({"rows": [_row("r3")]}),
            ]
            sent_params, _ = _drive_rows(manager, responses, endpoint="synthetic")
        assert len(sent_params) == 2

    def test_page_mode_resume_continues_the_total_count(self) -> None:
        # A resumed walk that restarted its row count at zero would keep requesting pages
        # past the total the crashed run already walked through.
        cfg = _synthetic_endpoint(pagination="page", page_size=2, total_key="total")
        with patch.dict(DECAGON_ENDPOINTS, {"synthetic": cfg}):
            manager = MagicMock(spec=ResumableSourceManager)
            manager.can_resume.return_value = True
            manager.load_state.return_value = DecagonResumeConfig(page=3, rows_walked=4)
            responses = [_make_response({"rows": [_row("r5")], "total": 5})]
            sent_params, _ = _drive_rows(manager, responses, endpoint="synthetic")
        assert sent_params == [{"page": "3", "page_size": "2"}]

    def test_offset_mode_advances_by_rows_received_and_terminates_on_total(self) -> None:
        cfg = _synthetic_endpoint(pagination="offset", page_size=2, total_key="total")
        with patch.dict(DECAGON_ENDPOINTS, {"synthetic": cfg}):
            manager = _fresh_manager()
            responses = [
                _make_response({"rows": [_row("r1"), _row("r2")], "total": 3}),
                _make_response({"rows": [_row("r3")], "total": 3}),
            ]
            sent_params, _ = _drive_rows(manager, responses, endpoint="synthetic")
        assert sent_params == [
            {"offset": "0", "limit": "2"},
            {"offset": "2", "limit": "2"},
        ]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [DecagonResumeConfig(offset=2)]

    def test_cursor_mode_has_more_false_ends_the_walk_even_with_a_cursor_present(self) -> None:
        # On endpoints that send has_more the flag is authoritative; following a leftover
        # cursor would re-fetch or spin on the final page.
        cfg = _synthetic_endpoint(pagination="cursor", next_cursor_keys=("next_cursor",), has_more_key="has_more")
        with patch.dict(DECAGON_ENDPOINTS, {"synthetic": cfg}):
            manager = _fresh_manager()
            responses = [
                _make_response({"rows": [_row("r1")], "next_cursor": "cur-1", "has_more": True}),
                _make_response({"rows": [_row("r2")], "next_cursor": "cur-stale", "has_more": False}),
            ]
            sent_params, _ = _drive_rows(manager, responses, endpoint="synthetic")
        assert sent_params == [{}, {"cursor": "cur-1"}]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [DecagonResumeConfig(cursor="cur-1")]

    def test_keyless_stream_yields_rows_without_touching_a_primary_key(self) -> None:
        # Streams with no documented id must not KeyError on a dedupe key they don't have.
        cfg = _synthetic_endpoint(pagination="single", primary_keys=None)
        with patch.dict(DECAGON_ENDPOINTS, {"synthetic": cfg}):
            manager = _fresh_manager()
            responses = [_make_response({"rows": [{"agent_name": "a"}, {"agent_name": "a"}]})]
            _, batches = _drive_rows(manager, responses, endpoint="synthetic")
        assert [len(b) for b in batches] == [2]

    def test_composite_primary_key_dedupes_on_all_fields(self) -> None:
        # Deduping on a subset of a composite key would silently drop distinct rows that
        # share that subset.
        cfg = _synthetic_endpoint(pagination="cursor", next_cursor_keys=("next_cursor",), primary_keys=["a", "b"])
        with patch.dict(DECAGON_ENDPOINTS, {"synthetic": cfg}):
            manager = _fresh_manager()
            responses = [
                _make_response({"rows": [{"a": 1, "b": 1}, {"a": 1, "b": 2}], "next_cursor": "c1"}),
                _make_response({"rows": [{"a": 1, "b": 2}, {"a": 2, "b": 1}], "next_cursor": None}),
            ]
            _, batches = _drive_rows(manager, responses, endpoint="synthetic")
        assert [len(b) for b in batches] == [2, 1]

    def test_iso8601_incremental_param_format(self) -> None:
        # Decagon's exports take epoch seconds but /admin_log/get types its bounds
        # differently; the format field exists so the two cannot be conflated.
        cfg = _synthetic_endpoint(
            pagination="single",
            incremental_param="start",
            incremental_param_format="iso8601",
        )
        with patch.dict(DECAGON_ENDPOINTS, {"synthetic": cfg}):
            manager = _fresh_manager()
            responses = [_make_response({"rows": [_row("r1")]})]
            sent_params, _ = _drive_rows(
                manager,
                responses,
                endpoint="synthetic",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 15, 12, 0, 5, tzinfo=UTC),
                incremental_field="created_at",
            )
        assert sent_params == [{"start": "2026-01-15T12:00:05+00:00"}]


class TestAgentAssistActions:
    def test_walk_sends_details_flag_and_window_and_pages_on_has_more(self) -> None:
        manager = _fresh_manager()
        watermark = datetime(2026, 1, 15, 12, 0, 5, tzinfo=UTC)
        # The bound is exclusive for this keyless stream: appends have no merge to dedupe
        # a re-fetched watermark second, which would otherwise re-import it every sync.
        epoch = str(int(watermark.timestamp()) + 1)
        responses = [
            _make_response(
                {
                    "events": [{"agent_name": "a", "action_name": "x", "ticket_id": "t1"}],
                    "has_more": True,
                    "next_cursor": "cur-1",
                }
            ),
            _make_response(
                {
                    "events": [{"agent_name": "b", "action_name": "y", "ticket_id": "t2"}],
                    "has_more": False,
                    "next_cursor": None,
                }
            ),
        ]
        sent_params, batches = _drive_rows(
            manager,
            responses,
            endpoint="agent_assist_actions",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
            incremental_field="created_at",
        )

        assert sent_params == [
            {"include_details": "true", "min_timestamp": epoch},
            {"include_details": "true", "min_timestamp": epoch, "cursor": "cur-1"},
        ]
        assert [len(b) for b in batches] == [1, 1]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [DecagonResumeConfig(cursor="cur-1", min_timestamp=int(epoch))]

    def test_source_response_is_a_keyless_append_stream(self) -> None:
        response = decagon_source(
            api_key="key",
            endpoint="agent_assist_actions",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(spec=ResumableSourceManager),
        )
        assert response.primary_keys is None
        assert response.partition_keys == ["created_at"]
        assert response.sort_mode == "desc"


class TestArticleTables:
    def test_articles_walk_pages_to_the_total_and_dedupes_shifted_rows(self) -> None:
        # The catalog can mutate between page fetches, so a row can shift pages mid-walk;
        # full-refresh writes are appends, so the shifted copy must be skipped.
        manager = _fresh_manager()
        responses = [
            _make_response({"articles": [{"id": 1}, {"id": 2}], "total": 3}),
            _make_response({"articles": [{"id": 2}, {"id": 3}], "total": 3}),
        ]
        sent_params, batches = _drive_rows(manager, responses, endpoint="articles")

        assert sent_params == [
            {"page": "1", "page_size": "100"},
            {"page": "2", "page_size": "100"},
        ]
        assert [[r["id"] for r in b] for b in batches] == [[1, 2], [3]]

    def test_shifted_duplicate_does_not_end_the_walk_before_the_total(self) -> None:
        # The server's total counts unique articles. A row that shifted pages arrives
        # twice but is kept once; counting raw items against the total would stop one
        # page early and silently drop the final page's articles.
        manager = _fresh_manager()
        responses = [
            _make_response({"articles": [{"id": 1}, {"id": 2}], "total": 4}),
            _make_response({"articles": [{"id": 2}, {"id": 3}], "total": 4}),
            _make_response({"articles": [{"id": 4}], "total": 4}),
        ]
        sent_params, batches = _drive_rows(manager, responses, endpoint="articles")

        assert len(sent_params) == 3
        assert [[r["id"] for r in b] for b in batches] == [[1, 2], [3], [4]]

    def test_page_contributing_nothing_new_ends_the_walk(self) -> None:
        # A server that ignores the page param would otherwise repeat the same page
        # forever without the kept-row count ever reaching the total.
        manager = _fresh_manager()
        responses = [
            _make_response({"articles": [{"id": 1}, {"id": 2}], "total": 10}),
            _make_response({"articles": [{"id": 1}, {"id": 2}], "total": 10}),
        ]
        sent_params, batches = _drive_rows(manager, responses, endpoint="articles")

        assert len(sent_params) == 2
        assert [[r["id"] for r in b] for b in batches] == [[1, 2]]

    def test_article_usage_is_a_single_request_pinned_to_utc(self) -> None:
        # The timezone param changes how usage is bucketed; leaving it to the account
        # default would let a dashboard setting silently shift the numbers.
        manager = _fresh_manager()
        responses = [_make_response({"usage": [{"article_id": 1, "count": 5}]})]
        sent_params, batches = _drive_rows(manager, responses, endpoint="article_usage")

        assert sent_params == [{"timezone": "UTC"}]
        assert [len(b) for b in batches] == [1]
        manager.save_state.assert_not_called()

    def test_articles_response_caps_batcher_chunks_for_document_rows(self) -> None:
        response = decagon_source(
            api_key="key",
            endpoint="articles",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(spec=ResumableSourceManager),
        )
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created_at"]
        assert response.chunk_size == 500
        assert response.chunk_size_bytes == 50 * 1024 * 1024

    def test_article_usage_response_is_keyless_and_unpartitioned(self) -> None:
        response = decagon_source(
            api_key="key",
            endpoint="article_usage",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(spec=ResumableSourceManager),
        )
        assert response.primary_keys is None
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestTags:
    def test_tags_is_a_single_request_with_counts(self) -> None:
        # get_counts populates human_count/total_count; dropping the param silently
        # empties both columns.
        manager = _fresh_manager()
        responses = [_make_response({"tags": [{"id": 1, "parent_id": None}, {"id": 2, "parent_id": 1}]})]
        sent_params, batches = _drive_rows(manager, responses, endpoint="tags")

        assert sent_params == [{"get_counts": "true"}]
        assert [[t["id"] for t in b] for b in batches] == [[1, 2]]
        manager.save_state.assert_not_called()

    def test_tags_response_is_unpartitioned_with_id_key(self) -> None:
        # Tags carry no timestamp; wiring the datetime partitioning every other stream
        # uses would fail the sync on a missing column.
        response = decagon_source(
            api_key="key",
            endpoint="tags",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(spec=ResumableSourceManager),
        )
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestAdminLogs:
    @parameterized.expand(
        [
            ("full_refresh", {}),
            (
                "first_incremental_run_without_watermark",
                {"should_use_incremental_field": True, "incremental_field": "created_at"},
            ),
        ]
    )
    def test_walk_without_a_watermark_still_sends_the_required_start_bound(
        self, _name: str, incremental_kwargs: dict[str, Any]
    ) -> None:
        # /admin_log/get 400s ("At least one of start or end dates is required") on a bare
        # request, so a full refresh or an incremental sync's first run must not omit it.
        manager = _fresh_manager()
        responses = [_make_response({"admin_logs": [{"id": "a1"}], "total": 1})]
        sent_params, batches = _drive_rows(manager, responses, endpoint="admin_logs", **incremental_kwargs)

        assert sent_params == [{"offset": "0", "limit": "100", "start": "1970-01-01T00:00:00+00:00"}]
        assert [len(b) for b in batches] == [1]

    def test_incremental_walk_sends_iso_start_and_pages_on_offset(self) -> None:
        # `start` takes a different value format from the exports' epoch min_timestamp;
        # sending an epoch here is the cross-endpoint confusion the spec warns about.
        manager = _fresh_manager()
        responses = [
            _make_response({"admin_logs": [{"id": "a1"}, {"id": "a2"}], "total": 3}),
            _make_response({"admin_logs": [{"id": "a3"}], "total": 3}),
        ]
        sent_params, batches = _drive_rows(
            manager,
            responses,
            endpoint="admin_logs",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 15, 12, 0, 5, tzinfo=UTC),
            incremental_field="created_at",
        )

        assert sent_params == [
            {"offset": "0", "limit": "100", "start": "2026-01-15T12:00:05+00:00"},
            {"offset": "2", "limit": "100", "start": "2026-01-15T12:00:05+00:00"},
        ]
        assert [len(b) for b in batches] == [2, 1]

    def test_response_merges_on_id_partitioned_by_created_at(self) -> None:
        response = decagon_source(
            api_key="key",
            endpoint="admin_logs",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(spec=ResumableSourceManager),
        )
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created_at"]
        assert response.sort_mode == "desc"


class TestTeamAndWatchtowerTables:
    def test_team_members_requests_invite_status_but_never_an_access_filter(self) -> None:
        # show_invite_status completes the roster with pending invites; sending `access`
        # could filter the roster down to one level and silently lose members.
        manager = _fresh_manager()
        responses = [_make_response({"members": [{"id": 1, "email": "a@example.com", "access": "admin"}]})]
        sent_params, batches = _drive_rows(manager, responses, endpoint="team_members")

        assert sent_params == [{"show_invite_status": "true"}]
        assert [len(b) for b in batches] == [1]

    def test_team_members_response_is_unpartitioned(self) -> None:
        # Members carry no timestamp; wiring the datetime partitioning every other stream
        # uses would fail the sync on a missing column.
        response = decagon_source(
            api_key="key",
            endpoint="team_members",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(spec=ResumableSourceManager),
        )
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None

    def test_watchtower_jobs_is_a_single_request_partitioned_by_created_at(self) -> None:
        manager = _fresh_manager()
        responses = [_make_response({"jobs": [{"id": 1, "name": "j", "created_at": "2026-01-01T00:00:00Z"}]})]
        sent_params, batches = _drive_rows(manager, responses, endpoint="watchtower_jobs")

        assert sent_params == [{}]
        assert [len(b) for b in batches] == [1]

        response = decagon_source(
            api_key="key",
            endpoint="watchtower_jobs",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(spec=ResumableSourceManager),
        )
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created_at"]


class TestToEpochSeconds:
    # The pipeline hands the DateTime watermark back as a datetime, a date, or an epoch
    # number depending on how it round-tripped through storage; the request boundary must
    # coerce all of them to the epoch seconds min_timestamp takes.
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 15, 12, 0, 5, tzinfo=UTC), 1768478405),
            ("naive_datetime_read_as_utc", datetime(2026, 1, 15, 12, 0, 5), 1768478405),
            (
                "subsecond_truncated_to_overlap_the_boundary",
                datetime(2026, 1, 15, 12, 0, 5, 999999, tzinfo=UTC),
                1768478405,
            ),
            ("date", date(2026, 1, 15), 1768435200),
            ("epoch_number_passthrough", 1768478405.9, 1768478405),
        ]
    )
    def test_coerces_watermark_types(self, _name: str, value: Any, expected: int) -> None:
        assert _to_epoch_seconds(value) == expected


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
