import json
import math
import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.decagon import (
    DECAGON_PAGE_SIZE,
    DecagonContractError,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.source import DecagonSource

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
    manager: MagicMock,
    responses: list[Response],
    endpoint: str = "conversations",
    logger: Optional[MagicMock] = None,
    **incremental_kwargs: Any,
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
    response_iter = iter(responses)
    return _drive_server(
        manager, lambda _params: next(response_iter), len(responses), endpoint, logger, **incremental_kwargs
    )


def _drive_server(
    manager: MagicMock,
    respond: Callable[[dict[str, Any]], Response],
    max_requests: int,
    endpoint: str = "conversations",
    logger: Optional[MagicMock] = None,
    **incremental_kwargs: Any,
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
    sent_params: list[dict[str, Any]] = []

    def fake_get(_url: str, *, params: dict[str, Any], **_kwargs: Any) -> Response:
        sent_params.append(dict(params or {}))
        if len(sent_params) > max_requests:
            raise AssertionError(f"walk did not stop within {max_requests} requests")
        return respond(sent_params[-1])

    with (
        patch(f"{DECAGON_MODULE}.make_tracked_session") as mock_session,
        patch(f"{DECAGON_MODULE}.time.sleep"),
    ):
        mock_session.return_value.get.side_effect = fake_get
        batches = list(
            get_rows(
                api_key="key",
                endpoint=endpoint,
                logger=logger or MagicMock(),
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

    def test_resume_seeds_cursor_from_saved_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = DecagonResumeConfig(cursor="cur-resumed")

        responses = [_make_response({"conversations": [_conversation("c9")], "next_page_cursor": None})]
        sent_params, yielded_ids = self._drive(manager, responses)

        assert sent_params == [{"cursor": "cur-resumed"}]
        assert yielded_ids == [["c9"]]

    def test_full_page_without_a_cursor_warns_that_the_walk_may_be_truncated(self) -> None:
        # Reading only a renamed cursor field already truncated this export once. A full
        # page that ends the walk is the one symptom left, so it has to reach the log.
        manager = self._fresh_manager()
        logger = MagicMock()
        page = [_conversation(f"c{i}") for i in range(DECAGON_PAGE_SIZE)]
        _drive_rows(manager, [_make_response({"conversations": page})], logger=logger)

        assert logger.warning.call_count == 1
        assert "ended on a full page" in logger.warning.call_args.args[0]

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

    @parameterized.expand([("rate_limited", 429), ("server_error", 500)])
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status_code: int) -> None:
        manager = self._fresh_manager()
        responses = [
            _make_response({}, status_code=status_code),
            _make_response({"conversations": [_conversation("c1")], "next_page_cursor": None}),
        ]
        _, yielded_ids = self._drive(manager, responses)
        assert yielded_ids == [["c1"]]


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
    def test_offset_mode_ignores_a_total_that_cannot_bound_the_walk(self) -> None:
        # Python counts True as 1, so a boolean total made the first row satisfy the bound
        # and the walk reported success on a partial table. An unusable total has to fall
        # back to short-page termination, as the page walk already does.
        cfg = _synthetic_endpoint(pagination="offset", page_size=2, total_key="total")
        with patch.dict(DECAGON_ENDPOINTS, {"synthetic": cfg}):
            manager = _fresh_manager()
            responses = [
                _make_response({"rows": [_row("r1"), _row("r2")], "total": True}),
                _make_response({"rows": [_row("r3")], "total": True}),
            ]
            _, batches = _drive_rows(manager, responses, endpoint="synthetic")

        assert [[r["id"] for r in b] for b in batches] == [["r1", "r2"], ["r3"]]

    def test_offset_mode_without_a_total_stops_at_the_constant_request_cap(self) -> None:
        # With no usable total the short page is the only natural end, and a server that
        # ignores `offset` never sends one: the walk then requests once a second until the
        # activity times out, burning a worker per attempt and inviting vendor throttling.
        cfg = _synthetic_endpoint(pagination="offset", page_size=2)
        cap = 7

        def respond(_params: dict[str, Any]) -> Response:
            return _make_response({"rows": [_row("r1"), _row("r2")]})

        logger = MagicMock()
        with (
            patch.dict(DECAGON_ENDPOINTS, {"synthetic": cfg}),
            patch(f"{DECAGON_MODULE}.MAX_PAGES_WITHOUT_TOTAL", cap),
        ):
            manager = _fresh_manager()
            sent_params, batches = _drive_server(manager, respond, cap, endpoint="synthetic", logger=logger)

        assert len(sent_params) == cap
        assert [[r["id"] for r in b] for b in batches] == [["r1", "r2"]]
        assert "offset" in logger.warning.call_args.args[0]

    @parameterized.expand(
        [
            (
                "carrying_no_next_page_cursor",
                [{"rows": [_row("r1")], "has_more": True}],
                "carried no next-page cursor",
            ),
            (
                "repeating_the_cursor_just_used",
                [
                    {"rows": [_row("r1")], "next_cursor": "cur-1", "has_more": True},
                    {"rows": [_row("r2")], "next_cursor": "cur-1", "has_more": True},
                ],
                "repeated the cursor just used",
            ),
        ]
    )
    def test_cursor_mode_logs_a_walk_that_ends_while_has_more_reports_rows(
        self, _name: str, bodies: list[dict[str, Any]], stopped: str
    ) -> None:
        # Following a missing or repeated cursor would re-fetch or spin, so stopping is
        # right, but the endpoints that send has_more append with no merge and walk desc:
        # a completed run moves the watermark past this page and every later sync skips
        # what the walk never reached. Silence here leaves a green job as the only trace.
        cfg = _synthetic_endpoint(pagination="cursor", next_cursor_keys=("next_cursor",), has_more_key="has_more")
        logger = MagicMock()
        with patch.dict(DECAGON_ENDPOINTS, {"synthetic": cfg}):
            manager = _fresh_manager()
            responses = [_make_response(body) for body in bodies]
            sent_params, batches = _drive_rows(manager, responses, endpoint="synthetic", logger=logger)

        assert len(sent_params) == len(bodies)
        assert [len(b) for b in batches] == [1] * len(bodies)
        logged = logger.warning.call_args.args[0]
        assert stopped in logged
        assert "'has_more' reports True" in logged


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

    def test_a_refused_details_add_on_retries_the_walk_without_it(self) -> None:
        # Detail export is entitled separately from the actions export, and a team without
        # it is refused the whole request, so the table only syncs if the walk drops the
        # param and retries.
        manager = _fresh_manager()
        responses = [
            _make_response({"detail": "detail export is not enabled for this team."}, status_code=403),
            _make_response({"events": [{"agent_name": "a"}], "has_more": False, "next_cursor": None}),
        ]
        sent_params, batches = _drive_rows(manager, responses, endpoint="agent_assist_actions")

        assert sent_params == [{"include_details": "true"}, {}]
        assert [len(b) for b in batches] == [1]

    def test_a_refused_details_add_on_stays_dropped_for_later_pages(self) -> None:
        manager = _fresh_manager()
        responses = [
            _make_response({}, status_code=403),
            _make_response({"events": [{"agent_name": "a"}], "has_more": True, "next_cursor": "cur-1"}),
            _make_response({"events": [{"agent_name": "b"}], "has_more": False, "next_cursor": None}),
        ]
        sent_params, batches = _drive_rows(manager, responses, endpoint="agent_assist_actions")

        assert sent_params == [{"include_details": "true"}, {}, {"cursor": "cur-1"}]
        assert [len(b) for b in batches] == [1, 1]

    def test_a_403_without_add_on_params_still_fails_the_walk(self) -> None:
        # The endpoint itself being refused must stay a failure rather than be swallowed
        # by the retry.
        manager = _fresh_manager()
        responses = [_make_response({}, status_code=403), _make_response({}, status_code=403)]
        with pytest.raises(HTTPError):
            _drive_rows(manager, responses, endpoint="agent_assist_actions")


class TestArticleTables:
    def test_server_that_ignores_the_page_param_fails_at_the_page_bound(self) -> None:
        # The same two rows come back on every request in a flipping order, so neither an
        # empty page nor the total nor a "same page as before" check would end the walk.
        # Completing at the bound would report success on a partial table, so the walk fails.
        cfg = dataclasses.replace(DECAGON_ENDPOINTS["articles"], page_size=2)
        rows = [{"id": 1}, {"id": 2}]
        max_pages = math.ceil(10 / 2) + 1
        sent_params: list[dict[str, Any]] = []

        def respond(params: dict[str, Any]) -> Response:
            sent_params.append(params)
            rows.reverse()
            return _make_response({"articles": list(rows), "total": 10})

        with patch.dict(DECAGON_ENDPOINTS, {"articles": cfg}):
            manager = _fresh_manager()
            with pytest.raises(DecagonContractError, match="honors the page param"):
                _drive_server(manager, respond, max_pages, endpoint="articles")

        assert [p["page"] for p in sent_params] == [str(n) for n in range(1, max_pages + 1)]

    @parameterized.expand([("negative", -1), ("boolean", True), ("string", "3"), ("null", None)])
    def test_malformed_total_falls_back_to_short_page_termination(self, _name: str, total: Any) -> None:
        # A total that cannot bound the walk must not end it early: a negative or boolean
        # total is below the kept-row count at once. (NaN and Infinity never arrive here;
        # the JSON parser rejects them.)
        cfg = dataclasses.replace(DECAGON_ENDPOINTS["articles"], page_size=2)
        with patch.dict(DECAGON_ENDPOINTS, {"articles": cfg}):
            manager = _fresh_manager()
            responses = [
                _make_response({"articles": [{"id": 1}, {"id": 2}], "total": total}),
                _make_response({"articles": [{"id": 3}], "total": total}),
            ]
            sent_params, batches = _drive_rows(manager, responses, endpoint="articles")

        assert len(sent_params) == 2
        assert [[r["id"] for r in b] for b in batches] == [[1, 2], [3]]

    @parameterized.expand(
        [
            ("only_list", {"data": [{"id": 1}, {"id": 2}], "total": 2}),
            ("configured_key_one_level_down", {"result": {"articles": [{"id": 1}, {"id": 2}]}, "total": 2}),
            ("only_list_one_level_down", {"result": {"items": [{"id": 1}, {"id": 2}]}, "total": 2}),
            (
                "only_list_carrying_the_primary_key",
                {"items": [{"id": 1}, {"id": 2}], "warnings": ["stale"], "total": 2},
            ),
        ]
    )
    def test_rows_are_read_from_a_renamed_or_re_nested_envelope(self, _name: str, body: dict[str, Any]) -> None:
        # A renamed or re-nested envelope key otherwise reads as an empty page, which fails
        # the walk against the reported total and leaves the table empty until support
        # updates the config.
        manager = _fresh_manager()
        _, batches = _drive_rows(manager, [_make_response(body)], endpoint="articles")

        assert [[r["id"] for r in b] for b in batches] == [[1, 2]]

    @parameterized.expand(
        [
            (
                "two_lists_that_both_look_like_rows",
                {"drafts": [{"id": 1}], "published": [{"id": 2}], "total": 2},
                "2 of them carry this endpoint's primary keys ('drafts', 'published')",
            ),
            (
                "two_lists_carrying_the_configured_name",
                {"result": {"articles": [{"id": 1}]}, "backup": {"articles": [{"id": 2}]}},
                "2 of them are named 'articles' ('result.articles', 'backup.articles')",
            ),
            (
                "a_later_item_without_the_primary_key",
                {"items": [{"id": 1}, {"slug": "x"}], "tags": [], "total": 2},
                "none of them is named 'articles' or carries this endpoint's primary keys",
            ),
            (
                "an_empty_list_beside_a_list_carrying_the_primary_key",
                {"data": [], "tags": [{"id": 7}], "total": 0},
                "only 'tags' carries this endpoint's primary keys",
            ),
            (
                "the_only_list_carrying_no_primary_key",
                {"warnings": [{"message": "partial"}], "total": 2},
                "none of them is named 'articles' or carries this endpoint's primary keys",
            ),
            (
                "one_list_one_level_down_carrying_no_primary_key",
                {"meta": {"warnings": [{"m": 1}]}, "total": 2},
                "none of them is named 'articles' or carries this endpoint's primary keys",
            ),
        ]
    )
    def test_an_ambiguous_envelope_fails_rather_than_guessing_a_list(
        self, _name: str, body: dict[str, Any], reason: str
    ) -> None:
        # Picking one of these would import the wrong table silently, or pick a list whose
        # later rows have no primary key and crash the deduplicator. Being the envelope's
        # only list is not evidence either: a list of warnings fits that description. An
        # empty list is a second reading of its own, because the renamed rows can be the
        # empty one. The walk keeps nothing and the contract guard fails the sync instead.
        # Support reads this failure without a Decagon credential to check it against, so
        # two lists matching has to read as two lists matching, not as a response with no
        # rows in it.
        manager = _fresh_manager()
        logger = MagicMock()

        with pytest.raises(DecagonContractError) as excinfo:
            _drive_rows(manager, [_make_response(body)], endpoint="articles", logger=logger)

        assert reason in str(excinfo.value)
        assert reason in logger.error.call_args.args[0]

    def test_an_unreadable_envelope_fails_a_cursor_walk_too(self) -> None:
        # The contract guard has to hold for every pagination mode. Reading the total only
        # in the paged modes left it inert everywhere else, so an unreadable envelope
        # completed as an empty sync.
        cfg = dataclasses.replace(DECAGON_ENDPOINTS["conversations"], total_key="total")
        with patch.dict(DECAGON_ENDPOINTS, {"conversations": cfg}):
            manager = _fresh_manager()
            responses = [_make_response({"unexpected": {"conversation_id": "c1"}, "total": 12})]

            with pytest.raises(DecagonContractError):
                _drive_rows(manager, responses, endpoint="conversations")

    @parameterized.expand(
        [
            ("two_lists", {"data": [{"article_id": 1}], "meta": [{"page": 1}]}),
            ("the_only_list", {"data": [{"article_id": 1}]}),
            ("one_list_one_level_down", {"result": {"warnings": [{"message": "partial"}]}}),
        ]
    )
    def test_a_keyless_table_fails_rather_than_reading_a_guessed_list(self, _name: str, body: dict[str, Any]) -> None:
        # article_usage appends without a merge, so a guessed list lands rows no later sync
        # can clean up. With no primary key to recognize rows by, no list qualifies, and the
        # endpoint reports no total, so completing would replace the table with nothing.
        manager = _fresh_manager()

        with pytest.raises(DecagonContractError):
            _drive_rows(manager, [_make_response(body)], endpoint="article_usage")

    def test_no_rows_against_a_nonzero_total_fails_the_sync(self) -> None:
        # The endpoint reports articles and the walk kept none, so the config no longer
        # matches the response. Completing here is what kept the table empty silently.
        manager = _fresh_manager()
        logger = MagicMock()
        responses = [_make_response({"unexpected": {"id": 1}, "total": 12})]

        with pytest.raises(DecagonContractError) as excinfo:
            _drive_rows(manager, responses, endpoint="articles", logger=logger)

        # Finalization replaces the raised message with the fixed operator-facing one, so
        # the shape reaches support through the log or not at all.
        assert "unexpected: object(id)" in logger.error.call_args.args[0]

        # Support cannot read the Decagon account, so the shape the walk saw has to travel
        # with the failure; without it the next envelope change needs a live credential to
        # diagnose.
        assert "unexpected: object(id)" in str(excinfo.value)
        assert "total: int" in str(excinfo.value)
        # The failure is deterministic, so the source must classify the message it actually
        # raises. An unclassified message repeats this identical request for the whole attempt
        # budget, reports it every time, and leaves the schema enabled for the next schedule.
        assert error_message_matches(str(excinfo.value), DecagonSource().get_non_retryable_errors())

    @parameterized.expand(
        [
            ("beside_the_nested_rows", {"result": {"articles": [{"id": 1}, {"id": 2}], "total": 2}}),
            ("left_at_the_top_level", {"result": {"articles": [{"id": 1}, {"id": 2}]}, "total": 2}),
        ]
    )
    def test_a_wrapped_envelope_bounds_the_page_walk_on_its_total(self, _name: str, body: dict[str, Any]) -> None:
        # A wrapper can take the total down with the rows or leave it outside, so the walk
        # reads it from the object that held the rows and falls back to the response. With
        # neither read finding it, a full page keeps requesting pages the export has ended.
        cfg = dataclasses.replace(DECAGON_ENDPOINTS["articles"], page_size=2)
        with patch.dict(DECAGON_ENDPOINTS, {"articles": cfg}):
            manager = _fresh_manager()
            sent_params, batches = _drive_rows(manager, [_make_response(body)], endpoint="articles")

        assert len(sent_params) == 1
        assert [[r["id"] for r in b] for b in batches] == [[1, 2]]

    def test_an_empty_knowledge_base_still_completes(self) -> None:
        manager = _fresh_manager()
        responses = [_make_response({"articles": [], "total": 0})]
        _, batches = _drive_rows(manager, responses, endpoint="articles")

        assert batches == []

    def test_a_table_without_a_total_also_fails_on_an_unreadable_envelope(self) -> None:
        # /tag/all reports no total, so the contract check that covers articles cannot see
        # this failure. The table is full refresh, and the pipeline clears it before the walk
        # runs, so completing with no rows leaves the tag dimension empty and the job green.
        manager = _fresh_manager()
        responses = [_make_response({"drafts": [{"slug": "a"}], "published": [{"slug": "b"}]})]

        with pytest.raises(DecagonContractError) as excinfo:
            _drive_rows(manager, responses, endpoint="tags")

        # Unclassified, this identical request repeats for the whole attempt budget and the
        # schema stays enabled to repeat it on the next schedule.
        assert error_message_matches(str(excinfo.value), DecagonSource().get_non_retryable_errors())
        assert "drafts: list[1]" in str(excinfo.value)


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

    @parameterized.expand(
        [
            ("full_refresh", {}),
            (
                "first_incremental_run_without_watermark",
                {"should_use_incremental_field": True, "incremental_field": "created_at"},
            ),
        ]
    )
    def test_no_rows_against_a_nonzero_total_fails_the_sync(
        self, _name: str, incremental_kwargs: dict[str, Any]
    ) -> None:
        # The mandatory `start` bound is the epoch in both modes, so the request covered every
        # row and keeping none against a positive total means the envelope no longer matches.
        # The bound must not read as a server-side window and excuse the empty walk.
        manager = _fresh_manager()
        responses = [_make_response({"unexpected": {"id": "a1"}, "total": 12})]

        with pytest.raises(DecagonContractError):
            _drive_rows(manager, responses, endpoint="admin_logs", **incremental_kwargs)


class TestTeamAndWatchtowerTables:
    def test_team_members_requests_invite_status_but_never_an_access_filter(self) -> None:
        # show_invite_status completes the roster with pending invites; sending `access`
        # could filter the roster down to one level and silently lose members.
        manager = _fresh_manager()
        responses = [_make_response({"members": [{"id": 1, "email": "a@example.com", "access": "admin"}]})]
        sent_params, batches = _drive_rows(manager, responses, endpoint="team_members")

        assert sent_params == [{"show_invite_status": "true"}]
        assert [len(b) for b in batches] == [1]

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
