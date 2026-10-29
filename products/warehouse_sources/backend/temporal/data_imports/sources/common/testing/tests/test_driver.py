import sys
import types
import dataclasses
from collections.abc import Iterator
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
import structlog
from asgiref.sync import async_to_sync

from products.warehouse_sources.backend.facade.source_config import SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common import config as source_config
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    always,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.types import ExternalDataSourceType

_BASE_URL = "https://double.example.com"
# The cursor the double saves once it has no rows left. Nothing is yielded after it, so the pipeline
# never confirms it and it must not persist.
_AFTER_THE_LAST_ROW = 999


@source_config.config
class _DoubleConfig(source_config.Config):
    token: str


@dataclasses.dataclass(frozen=True)
class _Cursor:
    page: int = 0


class _DoubleSource(ResumableSource[_DoubleConfig, _Cursor]):
    """A source with just enough behaviour to show what the driver records."""

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZYLO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(name="Double", label="Double", iconPath="/static/double.png", fields=[])

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[_Cursor]:
        return ResumableSourceManager(inputs, _Cursor)

    def source_for_pipeline(
        self,
        config: _DoubleConfig,
        resumable_source_manager: ResumableSourceManager[_Cursor],
        inputs: SourceInputs,
    ) -> SourceResponse:
        webhooks = WebhookSourceManager(inputs, structlog.get_logger())

        def items() -> Iterator[Any]:
            if async_to_sync(webhooks.webhook_enabled)():
                return
            start = 0
            if resumable_source_manager.can_resume():
                saved = resumable_source_manager.load_state()
                start = saved.page if saved is not None else 0
            session = make_tracked_session(redact_values=(config.token,))
            page = start
            while True:
                answer = session.get(f"{_BASE_URL}/rows", params={"page": str(page)}, timeout=(5, 5))
                rows = answer.json()["rows"]
                if not rows:
                    break
                page += 1
                resumable_source_manager.save_state(_Cursor(page=page))
                yield rows
            resumable_source_manager.save_state(_Cursor(page=_AFTER_THE_LAST_ROW))

        name = inputs.schema_name if inputs.api_version is None else f"{inputs.schema_name}@{inputs.api_version}"
        return SourceResponse(
            name=name, items=items, primary_keys=["id"], on_complete=resumable_source_manager.clear_state
        )


def _driver() -> SourceDriver:
    return SourceDriver(_DoubleSource(), _DoubleConfig(token="t"))


def _page(*ids: int) -> ScriptedResponse:
    return ScriptedResponse(json={"rows": [{"id": i} for i in ids]})


class TestSourceDriver:
    def test_a_cursor_saved_after_the_last_row_does_not_persist(self) -> None:
        result = _driver().run("rows", [_page(1), _page(2), _page()])

        assert result.rows == [{"id": 1}, {"id": 2}]
        assert [cursor.page for cursor in result.saved_states] == [1, 2, _AFTER_THE_LAST_ROW]
        # The pipeline confirms a cursor when it takes a row, so the last save never reaches storage.
        assert [cursor.page for cursor in result.committed_states] == [1, 2]

    def test_a_resume_state_is_what_the_source_loads(self) -> None:
        result = _driver().run("rows", [_page(7), _page()], resume_state=_Cursor(page=4))

        assert result.params("page") == ["4", "5"]
        assert result.rows == [{"id": 7}]

    def test_a_run_with_no_resume_state_starts_from_the_beginning(self) -> None:
        result = _driver().run("rows", [_page()])

        assert result.params("page") == ["0"]

    def test_a_request_the_script_does_not_answer_fails_the_run(self) -> None:
        # A source that keeps paging is the failure a pagination test looks for, so the driver must
        # raise rather than answer an empty page and let the loop end quietly.
        result = _driver().run("rows", [_page(1)])

        assert isinstance(result.raised, UnexpectedRequest)
        assert "page=1" in str(result.raised)

    def test_the_recorded_request_carries_the_url_query_and_headers(self) -> None:
        result = _driver().run("rows", [_page()])

        request = result.requests[0]
        assert request.method == "GET"
        assert request.path == "/rows"
        assert request.url == f"{_BASE_URL}/rows?page=0"
        assert request.param("page") == "0"
        assert request.headers["host"] == "double.example.com"

    def test_the_result_carries_what_source_for_pipeline_returned(self) -> None:
        result = _driver().run("rows", [_page()], api_version="2026-01-01")

        assert result.response is not None
        assert result.response.name == "rows@2026-01-01"
        assert result.response.primary_keys == ["id"]

    def test_the_result_carries_the_options_of_each_session(self) -> None:
        # A source passes its secrets to the session for redaction. The session is real here, so
        # the options are the only place a test can see them.
        result = _driver().run("rows", [_page()])

        assert result.session_options == [{"redact_values": ("t",)}]

    def test_a_run_nested_in_a_scripted_network_records_its_sessions_and_leaves_later_runs_recording(self) -> None:
        with patch.dict(sys.modules):
            with scripted_network([]) as outer:
                sys.modules["_imported_while_patched"] = types.ModuleType("_imported_while_patched")
                nested = _driver().run("rows", [_page()])
            later = _driver().run("rows", [_page()])

        assert (outer.session_options, nested.session_options, later.session_options) == (
            [],
            [{"redact_values": ("t",)}],
            [{"redact_values": ("t",)}],
        )

    def test_an_exception_in_the_script_fails_the_request_as_a_dropped_connection_does(self) -> None:
        def dropped(_request: Any) -> ScriptedResponse:
            raise ConnectionResetError("reset by peer")

        result = _driver().run("rows", dropped)

        assert isinstance(result.raised, requests.ConnectionError)

    def test_a_retried_status_needs_an_answer_for_each_try(self) -> None:
        # The stack below the source retries a 503. One scripted answer runs out on the first
        # retry, and `always` answers every try.
        once = _driver().run("rows", [ScriptedResponse(status=503)])
        every_time = _driver().run("rows", always(ScriptedResponse(status=503)))

        assert isinstance(once.raised, UnexpectedRequest)
        assert len(every_time.requests) > 1
        assert not isinstance(every_time.raised, UnexpectedRequest)

    def test_a_dropped_connection_is_retried_and_always_repeats_it(self) -> None:
        result = _driver().run("rows", always(ConnectionResetError("reset by peer")))

        assert len(result.requests) > 1
        assert isinstance(result.raised, requests.ConnectionError)

    def test_the_result_carries_the_cursor_left_in_storage(self) -> None:
        result = _driver().run("rows", [_page(1), _page()])

        # The double saves a cursor after its last row, which never commits, so page 1 stays stored.
        assert result.final_state == _Cursor(page=1)

    def test_a_long_walk_is_not_cut_short(self) -> None:
        pages = [_page(i) for i in range(1, 60)] + [_page()]

        result = _driver().run("rows", pages)

        assert result.raised is None
        assert len(result.rows) == 59

    def test_the_completion_hook_runs_after_a_clean_run(self) -> None:
        result = _driver().run("rows", [_page(1), _page()])

        assert result.final_state == _Cursor(page=1)
        assert result.completed_state is None

    def test_the_completion_hook_does_not_run_after_a_failed_run(self) -> None:
        result = _driver().run("rows", [_page(1)])

        assert isinstance(result.raised, UnexpectedRequest)
        assert result.completed_state == _Cursor(page=1)

    def test_a_source_that_can_read_webhook_rows_polls_the_api(self) -> None:
        # The webhook check reads the database, which the driver blocks, so the driver answers it.
        result = _driver().run("rows", [_page(1), _page()])

        assert result.raised is None
        assert result.rows == [{"id": 1}]

    def test_a_webhook_check_the_test_patched_keeps_its_answer(self) -> None:
        async def webhook_live(self: WebhookSourceManager, webhook_only: bool = False) -> bool:
            return True

        with patch.object(WebhookSourceManager, "webhook_enabled", webhook_live):
            result = _driver().run("rows", [])

        assert result.raised is None
        assert result.requests == []

    @pytest.mark.parametrize(
        ("should_use_incremental_field", "incremental_field", "expected"),
        [
            (None, None, False),
            (None, "updated_at", True),
            (False, "updated_at", False),
            (True, None, True),
        ],
    )
    def test_an_incremental_sync_follows_the_field_unless_set(
        self, should_use_incremental_field: bool | None, incremental_field: str | None, expected: bool
    ) -> None:
        inputs = source_inputs(
            "rows", should_use_incremental_field=should_use_incremental_field, incremental_field=incremental_field
        )

        assert inputs.should_use_incremental_field is expected

    def test_a_logger_reaches_the_source_inputs(self) -> None:
        logger = MagicMock()

        assert source_inputs("rows", logger=logger).logger is logger


class TestScriptedResponse:
    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            (ScriptedResponse(), b""),
            (ScriptedResponse(json={"a": 1}), b'{"a": 1}'),
            (ScriptedResponse(body=b"not json"), b"not json"),
        ],
    )
    def test_the_body_is_what_the_answer_declares(self, response: ScriptedResponse, expected: bytes) -> None:
        assert response.to_bytes().endswith(expected)
