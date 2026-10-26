import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.torii import ToriiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.torii.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.torii.source import ToriiSource
from products.warehouse_sources.backend.temporal.data_imports.sources.torii.torii import ToriiResumeConfig

_DATA_SELECTOR = {
    "Apps": "apps",
    "Users": "users",
    "Contracts": "contracts",
    "Transactions": "transactions",
}


class TestToriiSourceResumeBehavior:
    """End-to-end pagination/resume behaviour of ``ToriiSource``, driven through ``source_for_pipeline``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(ToriiSource(), ToriiSourceConfig(api_key="test-key"))

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_fresh_run_saves_cursor_after_each_non_terminal_page(self, endpoint: str) -> None:
        key = _DATA_SELECTOR[endpoint]

        result = self._driver().run(
            endpoint,
            [
                ScriptedResponse(json={key: [{"id": "1"}], "count": 1, "total": 3, "nextCursor": "cursor-1"}),
                ScriptedResponse(json={key: [{"id": "2"}], "count": 1, "total": 3, "nextCursor": "cursor-2"}),
                ScriptedResponse(json={key: [{"id": "3"}], "count": 1, "total": 3}),
            ],
        )

        assert result.params("cursor") == [None, "cursor-1", "cursor-2"]
        assert result.saved_states == [
            ToriiResumeConfig(cursor="cursor-1"),
            ToriiResumeConfig(cursor="cursor-2"),
        ]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        result = self._driver().run(
            "Apps",
            [ScriptedResponse(json={"apps": [{"id": "only"}]})],
            resume_state=ToriiResumeConfig(cursor="cursor-resumed"),
        )

        assert result.params("cursor") == ["cursor-resumed"]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = self._driver().run("Apps", [ScriptedResponse(json={"apps": [{"id": "a"}]})])

        assert result.params("cursor") == [None]
