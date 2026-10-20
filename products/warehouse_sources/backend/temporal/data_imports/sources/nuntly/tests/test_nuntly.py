from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nuntly import NuntlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.nuntly import (
    NuntlyResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.source import NuntlySource


class TestNuntlySourceResumeBehavior:
    """End-to-end cursor pagination + resume behaviour of ``NuntlySource``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(NuntlySource(), NuntlySourceConfig(api_key="apk_test"))

    @staticmethod
    def _page(rows: list[dict[str, Any]], next_cursor: str | None) -> ScriptedResponse:
        return ScriptedResponse(json={"data": rows, "nextCursor": next_cursor})

    @parameterized.expand([("Emails",), ("Messages",), ("Inboxes",), ("Domains",), ("Webhooks",)])
    def test_fresh_run_walks_pages_and_saves_cursor_after_each_non_terminal_page(self, endpoint: str) -> None:
        result = self._driver().run(
            endpoint,
            [
                self._page([{"id": "1"}], "cursor-1"),
                self._page([{"id": "2"}], "cursor-2"),
                self._page([{"id": "3"}], None),
            ],
        )

        assert result.raised is None
        assert result.params("cursor") == [None, "cursor-1", "cursor-2"]
        assert result.params("limit") == ["30", "30", "30"]
        assert all(url.startswith(f"https://api.nuntly.com{ENDPOINTS[endpoint].path}") for url in result.urls)
        assert result.saved_states == [
            NuntlyResumeConfig(cursor="cursor-1"),
            NuntlyResumeConfig(cursor="cursor-2"),
        ]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        result = self._driver().run(
            "Emails",
            [self._page([{"id": "4"}], None)],
            resume_state=NuntlyResumeConfig(cursor="cursor-resumed"),
        )

        assert result.raised is None
        assert result.params("cursor") == ["cursor-resumed"]

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = self._driver().run("Emails", [self._page([{"id": "a"}], None)])

        assert result.raised is None
        assert result.params("cursor") == [None]

    @parameterized.expand([("Emails",), ("Messages",), ("Inboxes",), ("Domains",), ("Webhooks",)])
    def test_source_response_uses_declared_primary_keys_and_partitioning(self, endpoint: str) -> None:
        result = self._driver().run(endpoint, [self._page([], None)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["createdAt"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True),
        ]
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, code = validate_credentials("apk_test")

        assert (is_valid, code) == (expected_valid, status_code)
        assert network.requests_log[0].path == "/emails"


class TestEndpointSettings:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_every_declared_endpoint_has_a_settings_entry(self, endpoint: str) -> None:
        assert ENDPOINTS[endpoint].path.startswith("/")
        assert ENDPOINTS[endpoint].primary_keys == ["id"]
