from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.svix import SvixSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.svix.source import SvixSource
from products.warehouse_sources.backend.temporal.data_imports.sources.svix.svix import (
    SvixResumeConfig,
    check_access,
    validate_credentials,
)


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


class TestCheckAccess:
    @pytest.mark.parametrize(
        "status, expected",
        [
            (200, (200, None)),
            (401, (401, None)),
            (403, (403, None)),
            (500, (500, "Svix returned HTTP 500")),
        ],
    )
    def test_status_mapping(self, status: int, expected: tuple[int, str | None]) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            assert check_access("sk-key") == expected

    def test_connection_error_maps_to_zero(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            status, message = check_access("sk-key")
        assert status == 0
        assert message == "Could not connect to Svix"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Svix API key"),
            (403, False, "Invalid Svix API key"),
            (500, False, "Svix returned HTTP 500"),
        ],
    )
    def test_validate_credentials(self, status: int, expected_valid: bool, expected_message: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            assert validate_credentials("sk-key") == (expected_valid, expected_message)
