from datetime import UTC, date, datetime
from typing import Any, cast

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mercury import (
    MercurySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercury.mercury import (
    MercuryResumeConfig,
    format_incremental_value,
    get_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercury.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mercury.source import MercurySource


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, None),
            (datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02"),
            (datetime(2026, 1, 2, 3, 4, 5), "2026-01-02"),
            (date(2026, 1, 2), "2026-01-02"),
            ("2026-01-02T03:04:05Z", "2026-01-02"),
        ],
    )
    def test_formats_watermark_for_the_api(self, value: Any, expected: str | None) -> None:
        assert format_incremental_value(value) == expected


class TestGetResource:
    @pytest.mark.parametrize("endpoint", [name for name in ENDPOINTS if name != "Transactions"])
    def test_full_refresh_endpoints_never_get_incremental_params(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=True)

        endpoint_config = cast(dict[str, Any], resource["endpoint"])
        assert not any(
            isinstance(value, dict) and value.get("type") == "incremental"
            for value in endpoint_config["params"].values()
        )


class TestMercurySourceResumeBehavior:
    """End-to-end pagination and resume behaviour of ``MercurySource``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(MercurySource(), MercurySourceConfig(api_key="test-token"))

    @staticmethod
    def _page(rows: list[dict[str, Any]], next_page: str | None) -> ScriptedResponse:
        return ScriptedResponse(json={"transactions": rows, "page": {"nextPage": next_page}})

    def test_fresh_run_saves_cursor_after_each_non_terminal_page(self) -> None:
        result = self._driver().run(
            "Transactions",
            [
                self._page([{"id": "t1"}], "t1"),
                self._page([{"id": "t2"}], "t2"),
                self._page([{"id": "t3"}], None),
            ],
        )

        assert result.raised is None
        assert result.params("start_after") == [None, "t1", "t2"]
        assert [row["id"] for row in result.rows] == ["t1", "t2", "t3"]
        assert result.saved_states == [
            MercuryResumeConfig(cursor="t1"),
            MercuryResumeConfig(cursor="t2"),
        ]
        assert result.committed_states == result.saved_states

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        result = self._driver().run(
            "Transactions",
            [self._page([{"id": "t43"}], None)],
            resume_state=MercuryResumeConfig(cursor="t42"),
        )

        assert result.raised is None
        assert result.params("start_after") == ["t42"]

    def test_incremental_sync_sends_date_only_start_watermark(self) -> None:
        result = self._driver().run(
            "Transactions",
            [self._page([{"id": "t1"}], None)],
            incremental_field="createdAt",
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("start") == "2026-01-02"
        assert result.requests[0].param("order") == "asc"


class TestMercuryTopLevelEndpoints:
    @pytest.mark.parametrize(
        ("endpoint", "bodies", "expected_path", "expected_order", "expected_cursors", "expected_rows"),
        [
            (
                "SendMoneyApprovalRequests",
                [
                    {"requests": [{"requestId": "r1"}], "page": {"nextPage": "r1"}},
                    {"requests": [{"requestId": "r2"}], "page": {}},
                ],
                "/request-send-money",
                None,
                [None, "r1"],
                [{"requestId": "r1"}, {"requestId": "r2"}],
            ),
            (
                "RecipientInvites",
                [
                    {"invites": [{"id": "inv-1"}], "page": {"nextPage": "inv-1"}},
                    {"invites": [{"id": "inv-2"}], "page": {"nextPage": None}},
                ],
                "/recipients/invites",
                "asc",
                [None, "inv-1"],
                [{"id": "inv-1"}, {"id": "inv-2"}],
            ),
            (
                "SafeRequests",
                [[{"id": "safe-1"}, {"id": "safe-2"}]],
                "/safes",
                None,
                [None],
                [{"id": "safe-1"}, {"id": "safe-2"}],
            ),
            (
                "SafeRequests",
                [[]],
                "/safes",
                None,
                [None],
                [],
            ),
        ],
    )
    def test_walks_pages_to_the_terminal_page(
        self,
        endpoint: str,
        bodies: list[Any],
        expected_path: str,
        expected_order: str | None,
        expected_cursors: list[str | None],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = SourceDriver(MercurySource(), MercurySourceConfig(api_key="test-token")).run(
            endpoint, [ScriptedResponse(json=body) for body in bodies]
        )

        assert result.raised is None
        assert [request.path.split("/api/v1", 1)[-1] for request in result.requests] == [expected_path] * len(bodies)
        assert [request.param("order") for request in result.requests] == [expected_order] * len(bodies)
        assert result.params("start_after") == expected_cursors
        assert result.rows == expected_rows


class TestMercuryFanoutEndpoints:
    @pytest.mark.parametrize(
        (
            "endpoint",
            "parent_body",
            "child_bodies",
            "expected_paths",
            "cursor_param",
            "expected_cursors",
            "expected_rows",
        ),
        [
            (
                "AccountStatements",
                {"accounts": [{"id": "acc-1"}, {"id": "acc-2"}], "page": {"nextPage": None}},
                [
                    {"statements": [{"id": "s1"}], "page": {"nextPage": "s1"}},
                    {"statements": [{"id": "s2"}], "page": {}},
                    {"statements": [{"id": "s3"}], "page": {"nextPage": None}},
                ],
                ["/account/acc-1/statements", "/account/acc-1/statements", "/account/acc-2/statements"],
                "start_after",
                [None, "s1", None],
                [
                    {"id": "s1", "accountId": "acc-1"},
                    {"id": "s2", "accountId": "acc-1"},
                    {"id": "s3", "accountId": "acc-2"},
                ],
            ),
            (
                "TreasuryTransactions",
                {"accounts": [{"id": "tr-1"}, {"id": "tr-2"}], "page": {"nextPage": None}},
                [
                    {"transactions": [{"id": "t1", "accountId": "tr-1"}], "cursor": 7},
                    {"transactions": [{"id": "t2", "accountId": "tr-1"}], "cursor": None},
                    {"transactions": [{"id": "t3", "accountId": "tr-2"}]},
                ],
                ["/treasury/tr-1/transactions", "/treasury/tr-1/transactions", "/treasury/tr-2/transactions"],
                "cursor",
                [None, "7", None],
                [
                    {"id": "t1", "accountId": "tr-1"},
                    {"id": "t2", "accountId": "tr-1"},
                    {"id": "t3", "accountId": "tr-2"},
                ],
            ),
        ],
    )
    def test_walks_child_pages_for_each_parent_account(
        self,
        endpoint: str,
        parent_body: dict[str, Any],
        child_bodies: list[dict[str, Any]],
        expected_paths: list[str],
        cursor_param: str,
        expected_cursors: list[str | None],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = SourceDriver(MercurySource(), MercurySourceConfig(api_key="test-token")).run(
            endpoint, [ScriptedResponse(json=body) for body in [parent_body, *child_bodies]]
        )

        assert result.raised is None
        child_requests = result.requests[1:]
        assert [request.path.split("/api/v1", 1)[-1] for request in child_requests] == expected_paths
        assert [request.param(cursor_param) for request in child_requests] == expected_cursors
        assert all(request.param("order") == "asc" for request in child_requests)
        assert result.rows == expected_rows
        assert result.saved_states == []
