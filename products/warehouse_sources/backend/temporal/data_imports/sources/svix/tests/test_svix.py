from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.svix import SvixSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.svix.source import SvixSource
from products.warehouse_sources.backend.temporal.data_imports.sources.svix.svix import SvixResumeConfig


def _response(items: list[dict[str, Any]], iterator: str | None, done: bool) -> ScriptedResponse:
    return ScriptedResponse(json={"iterator": iterator, "done": done, "data": items})


def _driver() -> SourceDriver:
    return SourceDriver(SvixSource(), SvixSourceConfig(api_key="sk-key"))


class TestPagination:
    def test_follows_cursor_until_done(self) -> None:
        result = _driver().run(
            "applications",
            [
                _response([{"id": "app_1"}], iterator="c1", done=False),
                _response([{"id": "app_2"}], iterator="c2", done=True),
            ],
        )

        assert result.rows == [{"id": "app_1"}, {"id": "app_2"}]
        # First request carries no cursor; the second carries the cursor from page one.
        assert result.params("iterator") == [None, "c1"]
        # State saved once, carrying the cursor that fetches the second page (not the terminal one).
        assert result.saved_states == [SvixResumeConfig(iterator="c1")]

    def test_stops_when_iterator_missing(self) -> None:
        # A page that isn't `done` but returns no next cursor must still terminate.
        result = _driver().run("applications", [_response([{"id": "app_1"}], iterator=None, done=False)])

        assert result.rows == [{"id": "app_1"}]
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "applications",
            [_response([{"id": "app_2"}], iterator="c2", done=True)],
            resume_state=SvixResumeConfig(iterator="c1"),
        )

        # The first (cursorless) page must never be fetched on resume — one request, seeded with c1.
        assert result.rows == [{"id": "app_2"}]
        assert len(result.requests) == 1
        assert result.params("iterator") == ["c1"]
