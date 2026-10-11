from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)

from sources.zylo._config import ZyloSourceConfig
from sources.zylo.source import ZyloSource
from sources.zylo.zylo import (
    INITIAL_INCREMENTAL_VALUE,
    ZyloResumeConfig,
    _format_zylo_filter_date,
    probe_endpoint_status,
    validate_credentials,
)


class TestFormatZyloFilterDate:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02,gte"),
            (date(2024, 1, 2), "2024-01-02,gte"),
            ("2024-01-02 03:04:05", "2024-01-02,gte"),
            ("2024-01-02", "2024-01-02,gte"),
        ],
    )
    def test_formats_to_date_with_gte_suffix(self, value: Any, expected: str) -> None:
        assert _format_zylo_filter_date(value) == expected

    def test_unparseable_value_falls_back_to_raw_with_suffix(self) -> None:
        assert _format_zylo_filter_date("not-a-date") == "not-a-date,gte"


class TestZyloSourceResumeBehavior:
    """End-to-end resume behaviour of ``ZyloSource``, driven through ``source_for_pipeline``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(ZyloSource(), ZyloSourceConfig(token_id="tok_id", token_secret="tok_secret"))

    @staticmethod
    def _page(rows: list[dict[str, Any]]) -> ScriptedResponse:
        return ScriptedResponse(json=rows)

    def test_fresh_run_saves_skip_after_each_non_terminal_page(self) -> None:
        result = self._driver().run(
            "Applications",
            [
                self._page([{"id": f"app_{i}"} for i in range(1000)]),
                self._page([{"id": f"app_{i}"} for i in range(1000, 2000)]),
                self._page([{"id": "app_last"}]),
            ],
        )

        assert result.params("skip") == ["0", "1000", "2000"]
        assert result.params("limit") == ["1000", "1000", "1000"]
        assert result.saved_states == [ZyloResumeConfig(next_skip=1000), ZyloResumeConfig(next_skip=2000)]

    def test_resume_seeds_paginator_with_saved_skip(self) -> None:
        result = self._driver().run(
            "Applications",
            [self._page([{"id": "app_last"}])],
            resume_state=ZyloResumeConfig(next_skip=2000),
        )

        assert result.params("skip") == ["2000"]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = self._driver().run("Applications", [self._page([{"id": "a"}])])

        assert result.params("skip") == ["0"]

    def test_incremental_request_carries_gte_filter_and_sort(self) -> None:
        result = self._driver().run(
            "Contracts",
            [self._page([{"id": "contract_1"}])],
            incremental_field="zylo_created_at",
        )

        assert result.requests[0].param("zylo_created_at") == f"{INITIAL_INCREMENTAL_VALUE},gte"
        assert result.requests[0].param("sort") == "+zylo_created_at"

    def test_executions_fan_out_per_automation_with_incremental_filter(self) -> None:
        result = self._driver().run(
            "AutomationExecutions",
            [
                self._page([{"id": "auto_1"}, {"id": "auto_2"}]),
                self._page([{"id": f"exec_{i}", "automation_id": "auto_1"} for i in range(1000)]),
                self._page([{"id": "exec_last", "automation_id": "auto_1"}]),
                self._page([{"id": "exec_b", "automation_id": "auto_2"}]),
            ],
            incremental_field="zylo_modified_at",
            db_incremental_field_last_value=datetime(2026, 7, 21, 12, tzinfo=UTC),
        )

        assert result.paths == [
            "/v2/automations",
            "/v2/automations/auto_1/executions",
            "/v2/automations/auto_1/executions",
            "/v2/automations/auto_2/executions",
        ]
        assert result.requests[0].param("zylo_modified_at") is None
        assert result.params("skip")[1:] == ["0", "1000", "0"]
        for request in result.requests[1:]:
            assert request.param("zylo_modified_at") == "2026-07-21,gte"
            assert request.param("sort") == "+zylo_modified_at"
        assert len(result.rows) == 1002

    def test_executions_resume_skips_completed_automations(self) -> None:
        result = self._driver().run(
            "AutomationExecutions",
            [
                self._page([{"id": "auto_1"}, {"id": "auto_2"}]),
                self._page([{"id": "exec_b", "automation_id": "auto_2"}]),
            ],
            resume_state=ZyloResumeConfig(
                fanout_state={"completed": ["/v2/automations/auto_1/executions"], "current": None, "child_state": None}
            ),
        )

        assert result.paths == ["/v2/automations", "/v2/automations/auto_2/executions"]
        saved = result.saved_states[-1]
        assert saved.next_skip is None
        assert set(saved.fanout_state["completed"]) == {
            "/v2/automations/auto_1/executions",
            "/v2/automations/auto_2/executions",
        }


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @patch("sources.zylo.zylo.make_tracked_session")
    def test_status_code_mapping(self, mock_session: MagicMock, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("tok_id", "tok_secret") is expected

    @patch("sources.zylo.zylo.make_tracked_session")
    def test_network_error_returns_false(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("tok_id", "tok_secret") is False


class TestProbeEndpointStatus:
    @pytest.mark.parametrize("status_code", [200, 401, 403, 429, 500])
    @patch("sources.zylo.zylo.make_tracked_session")
    def test_returns_status_code(self, mock_session: MagicMock, status_code: int) -> None:
        response = MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert probe_endpoint_status("tok_id", "tok_secret", "/v2/purchaseOrders") == status_code

    @patch("sources.zylo.zylo.make_tracked_session")
    def test_network_error_returns_none(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert probe_endpoint_status("tok_id", "tok_secret", "/v2/purchaseOrders") is None
