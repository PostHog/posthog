from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.clever.clever import (
    CleverPaginator,
    CleverResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clever.settings import (
    CLEVER_API_VERSION_V3_0,
    CLEVER_API_VERSION_V3_1,
    clever_base_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clever.source import CleverSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clever import CleverSourceConfig


def _next_link(starting_after: str) -> dict[str, Any]:
    return {"rel": "next", "uri": f"/v3.0/districts?starting_after={starting_after}&limit=10000"}


class TestCleverPaginator:
    @pytest.mark.parametrize(
        "links",
        [
            [{"rel": "self", "uri": "/v3.0/districts"}],  # no `next` link at all
            [],  # empty links array
            [{"rel": "next", "uri": "/v3.0/districts?limit=10000"}],  # `next` link with no cursor value
        ],
    )
    def test_update_state_stops_when_no_resumable_next_link(self, links: list[dict[str, Any]]) -> None:
        paginator = CleverPaginator()
        response = MagicMock()
        response.json.return_value = {"data": [{"data": {"id": "d1"}}], "links": links}
        paginator.update_state(response)
        assert paginator._starting_after is None
        assert paginator.has_next_page is False

    def test_get_resume_state_returns_none_on_terminal_page(self) -> None:
        paginator = CleverPaginator()
        response = MagicMock()
        response.json.return_value = {"data": [], "links": []}
        paginator.update_state(response)

        assert paginator.get_resume_state() is None


class TestCleverSourceResumeBehavior:
    """End-to-end resume/incremental behaviour of ``CleverSource`` via ``source_for_pipeline``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(CleverSource(), CleverSourceConfig(bearer_token="test-token"))

    @staticmethod
    def _page(rows: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
        return ScriptedResponse(
            json={
                "data": [{"data": row} for row in rows],
                "links": [_next_link(next_cursor)] if next_cursor else [],
            }
        )

    @pytest.mark.parametrize("endpoint", ["Districts", "Schools", "Users", "Sections", "Courses", "Terms"])
    def test_fresh_full_refresh_run_saves_cursor_after_each_non_terminal_page(self, endpoint: str) -> None:
        result = self._driver().run(
            endpoint,
            [self._page([{"id": "r1"}], "r1"), self._page([{"id": "r2"}], "r2"), self._page([{"id": "r3"}])],
        )

        assert result.raised is None
        assert result.rows == [{"id": "r1"}, {"id": "r2"}, {"id": "r3"}]
        assert result.params("starting_after") == [None, "r1", "r2"]
        assert result.saved_states == [
            CleverResumeConfig(starting_after="r1"),
            CleverResumeConfig(starting_after="r2"),
        ]

    @pytest.mark.parametrize(
        ("api_version", "expected_url"),
        [
            (CLEVER_API_VERSION_V3_0, "https://api.clever.com/v3.0/users"),
            (CLEVER_API_VERSION_V3_1, "https://api.clever.com/v3.1/users"),
        ],
    )
    def test_requests_target_the_pinned_api_version(self, api_version: str, expected_url: str) -> None:
        result = self._driver().run(
            "Users", [self._page([{"id": "u1"}], "u1"), self._page([{"id": "u2"}])], api_version=api_version
        )

        assert result.raised is None
        assert [request.origin + request.path for request in result.requests] == [expected_url, expected_url]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        result = self._driver().run(
            "Districts", [self._page([{"id": "r4"}])], resume_state=CleverResumeConfig(starting_after="cursor-resumed")
        )

        assert result.raised is None
        assert result.params("starting_after") == ["cursor-resumed"]

    def test_incremental_seeds_from_db_last_value_when_no_saved_state(self) -> None:
        """Events has no mid-run resume state (fresh run), but a prior sync's watermark
        should seed `starting_after` so the delta feed continues from where it left off."""
        result = self._driver().run(
            "Events",
            [self._page([{"id": "evt-9"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value="evt-5",
        )

        assert result.raised is None
        assert result.params("starting_after") == ["evt-5"]

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = self._driver().run("Districts", [self._page([{"id": "a"}])])

        assert result.raised is None
        assert result.params("starting_after") == [None]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, message = validate_credentials("test-token", CLEVER_API_VERSION_V3_1)

        assert network.requests_log[0].path == "/v3.1/districts"
        assert is_valid is expected_valid
        if expected_valid:
            assert message is None
        else:
            assert message is not None

    def test_validate_credentials_redacts_token(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("super-secret-token", CLEVER_API_VERSION_V3_1)

        assert network.session_options == [{"redact_values": ("super-secret-token",)}]

    @pytest.mark.parametrize(
        ("api_version", "expected_url"),
        [
            (CLEVER_API_VERSION_V3_0, "https://api.clever.com/v3.0/districts"),
            (CLEVER_API_VERSION_V3_1, "https://api.clever.com/v3.1/districts"),
        ],
    )
    def test_validate_credentials_probes_the_requested_api_version(self, api_version: str, expected_url: str) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("test-token", api_version)

        assert network.requests_log[0].origin + network.requests_log[0].path == expected_url


def test_clever_base_url_rejects_unknown_version() -> None:
    # Falling back to another version would silently move a pinned source.
    with pytest.raises(ValueError):
        clever_base_url("v2.1")
