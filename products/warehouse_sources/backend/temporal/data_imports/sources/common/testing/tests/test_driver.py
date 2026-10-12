import dataclasses
from collections.abc import Iterator
from typing import Any

import pytest

from products.warehouse_sources.backend.facade.source_config import SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common import config as source_config
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
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
        def items() -> Iterator[Any]:
            start = 0
            if resumable_source_manager.can_resume():
                saved = resumable_source_manager.load_state()
                start = saved.page if saved is not None else 0
            session = make_tracked_session()
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

        return SourceResponse(name=inputs.schema_name, items=items, primary_keys=["id"])


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
