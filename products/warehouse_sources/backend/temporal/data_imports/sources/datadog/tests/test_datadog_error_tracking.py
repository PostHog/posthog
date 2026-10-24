import dataclasses
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.error_tracking import (
    DatadogIssueSearchConfig,
    _epoch_ms_to_iso,
    _join_included,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.settings import DATADOG_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.source import DatadogSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.datadog import (
    DatadogSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(
        DatadogSource(), DatadogSourceConfig(api_key="api", application_key="app", site="datadoghq.com")
    )


class TestWalkPageCap:
    @pytest.mark.parametrize(
        ("incremental", "expected_ids", "expected_warnings"),
        [
            # The next incremental sync continues from the checkpointed cursor value.
            (True, ["0", "1"], [("datadog.page_cap_reached",)]),
            # An oldest-first full refresh replaces the table, so a cap would drop the newest rows.
            (False, ["0", "1", "2", "3"], []),
        ],
    )
    def test_page_cap_applies_only_where_the_dropped_rows_come_back(
        self, incremental: bool, expected_ids: list[str], expected_warnings: list[tuple[str]]
    ) -> None:
        capped = dataclasses.replace(DATADOG_ENDPOINTS["error_logs"], max_pages_per_sync=2)
        pages = [
            {"data": [{"id": str(i), "attributes": {}}], "links": {"next": f"https://api.datadoghq.com/p{i + 1}"}}
            for i in range(3)
        ] + [{"data": [{"id": "3", "attributes": {}}], "links": {}}]
        logger = mock.MagicMock()

        with mock.patch.dict(DATADOG_ENDPOINTS, {"error_logs": capped}):
            result = _driver().run(
                "error_logs",
                [ScriptedResponse(json=page) for page in pages],
                logger=logger,
                should_use_incremental_field=incremental,
                incremental_field="timestamp" if incremental else None,
            )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == expected_ids
        assert [call.args for call in logger.warning.call_args_list] == expected_warnings


class TestSpanErrorType:
    @pytest.mark.parametrize(
        ("attributes", "expected"),
        [
            ({"custom": {"error": {"type": "TimeoutError", "message": "upstream"}}}, "TimeoutError"),
            ({"custom": {"error.type": "KeyError"}}, "KeyError"),
            ({"error": {"type": "ValueError"}}, "ValueError"),
            ({"custom": {"http": {"status_code": "500"}}}, None),
        ],
    )
    def test_sync_writes_the_error_type_wherever_the_span_keeps_it(
        self, attributes: dict[str, Any], expected: str | None
    ) -> None:
        span = {"id": "s1", "type": "spans", "attributes": {"service": "checkout-api", **attributes}}

        result = _driver().run("error_spans", [ScriptedResponse(json={"data": [span], "links": {}})])

        assert result.raised is None
        assert [row["error_type"] for row in result.rows] == [expected]


def _issue_result(issue_id: str, total: int, sessions: int = 1, users: int = 1) -> dict[str, Any]:
    return {
        "id": issue_id,
        "type": "error_tracking_search_result",
        "attributes": {"total_count": total, "impacted_sessions": sessions, "impacted_users": users},
        "relationships": {"issue": {"data": {"id": issue_id, "type": "issue"}}},
    }


def _issue_included(issue_id: str, last_seen: int, **attributes: Any) -> dict[str, Any]:
    return {
        "id": issue_id,
        "type": "issue",
        "attributes": {
            "error_type": "ConnectionError",
            "error_message": "Connection refused",
            "service": "checkout-api",
            "state": "OPEN",
            "first_seen": 1_772_593_094_123,
            "last_seen": last_seen,
            **attributes,
        },
    }


def _issue_response(*issues: tuple[str, int, int]) -> dict[str, Any]:
    """Build a search response from ``(issue id, total count, last_seen)`` tuples."""
    return {
        "data": [_issue_result(issue_id, total) for issue_id, total, _ in issues],
        "included": [_issue_included(issue_id, last_seen) for issue_id, _, last_seen in issues],
    }


class TestIssueSearch:
    @staticmethod
    def _run(script: list[ScriptedResponse], config_override: Any = None) -> tuple[DriveResult, mock.MagicMock]:
        logger = mock.MagicMock()
        endpoint_patch = {"error_tracking_issues": config_override} if config_override else {}
        with mock.patch.dict(DATADOG_ENDPOINTS, endpoint_patch):
            result = _driver().run("error_tracking_issues", script, logger=logger)
        assert result.raised is None
        return result, logger

    @staticmethod
    def _with_search(**overrides: Any) -> Any:
        base = DATADOG_ENDPOINTS["error_tracking_issues"]
        assert base.search is not None
        return dataclasses.replace(base, search=dataclasses.replace(base.search, **overrides))

    def test_posts_a_search_body_and_shapes_rows(self) -> None:
        result, _ = self._run([ScriptedResponse(json=_issue_response(("issue-1", 12, 1_772_679_494_000)))])

        assert [request.method for request in result.requests] == ["POST"]
        request = result.requests[0]
        assert request.path == "/api/v2/error-tracking/issues/search"
        assert request.param("include") == "issue"
        data = request.json()["data"]
        assert data["type"] == "search_request"
        attributes = data["attributes"]
        assert isinstance(attributes["from"], int)
        assert isinstance(attributes["to"], int)
        assert attributes["from"] < attributes["to"]

        # Attributes the response omits are still present, so the table keeps the same columns.
        assert result.rows == [
            {
                **dict.fromkeys(DatadogIssueSearchConfig().issue_fields),
                "id": "issue-1",
                "error_type": "ConnectionError",
                "error_message": "Connection refused",
                "service": "checkout-api",
                "state": "OPEN",
                "first_seen": "2026-03-04T02:58:14.123Z",
                "last_seen": "2026-03-05T02:58:14.000Z",
                "window_total_count": 12,
                "window_impacted_sessions": 1,
                "window_impacted_users": 1,
            }
        ]
        # A sync must not leave resume state behind that a later run would pick up.
        assert result.saved_states == []

    def test_full_response_halves_the_window_and_merges_by_issue(self) -> None:
        override = self._with_search(max_results_per_request=3)
        result, _ = self._run(
            [
                # The whole window comes back full, so it may hide issues.
                ScriptedResponse(
                    json=_issue_response(("issue-1", 1, 1_000), ("issue-2", 1, 1_000), ("issue-3", 1, 1_000))
                ),
                ScriptedResponse(
                    json={
                        "data": [_issue_result("issue-1", 3, users=5), _issue_result("issue-2", 5)],
                        "included": [_issue_included("issue-1", 1_000), _issue_included("issue-2", 2_000)],
                    }
                ),
                ScriptedResponse(
                    json={
                        "data": [_issue_result("issue-1", 4, users=2)],
                        "included": [_issue_included("issue-1", 9_000)],
                    }
                ),
            ],
            config_override=override,
        )

        assert len(result.requests) == 3
        whole, first, second = (request.json()["data"]["attributes"] for request in result.requests)
        # Earlier half first, and the halves tile the window with no gap or overlap.
        assert first["from"] == whole["from"]
        assert first["to"] == second["from"]
        assert second["to"] == whole["to"]

        by_id = {row["id"]: row for row in result.rows}
        assert set(by_id) == {"issue-1", "issue-2"}
        # Counts of the halves add up, and the full-window response is discarded, not double counted.
        assert by_id["issue-1"]["window_total_count"] == 7
        # A user can appear in both halves, so the distinct count is the larger half, not the sum.
        assert by_id["issue-1"]["window_impacted_users"] == 5
        assert by_id["issue-2"]["window_total_count"] == 5
        assert by_id["issue-1"]["last_seen"] == _epoch_ms_to_iso(9_000)

    def test_full_response_at_the_smallest_window_warns_and_keeps_rows(self) -> None:
        # Splitting stops at the minimum window. Dropping the rows silently would look like a
        # complete sync, so the cap is reported and the rows we got are kept.
        override = self._with_search(max_results_per_request=2, min_window_seconds=30 * 24 * 3600)
        result, logger = self._run(
            [ScriptedResponse(json=_issue_response(("issue-1", 1, 1_000), ("issue-2", 2, 1_000)))],
            config_override=override,
        )

        assert len(result.requests) == 1
        assert {row["id"] for row in result.rows} == {"issue-1", "issue-2"}
        logger.warning.assert_called_once()
        assert logger.warning.call_args.args == ("datadog.search_window_truncated",)
        assert logger.warning.call_args.kwargs["max_results"] == 2

    def test_request_cap_stops_splitting_and_warns(self) -> None:
        # Every response is full, so an unbounded sync would split down to the smallest window.
        override = self._with_search(max_results_per_request=1, max_requests_per_sync=5)
        result, logger = self._run(
            [ScriptedResponse(json=_issue_response(("issue-1", 1, 1_000)))] * 5, config_override=override
        )

        assert len(result.requests) <= 5
        assert {row["id"] for row in result.rows} == {"issue-1"}
        capped = [
            call for call in logger.warning.call_args_list if call.args == ("datadog.search_request_cap_reached",)
        ]
        assert capped
        assert capped[0].kwargs["max_requests"] == 5

    def test_transient_status_is_retried_on_post(self) -> None:
        # The transport retries only GET, so the POST search depends on the retry in fetch_page.
        result, _ = self._run(
            [ScriptedResponse(status=503), ScriptedResponse(json=_issue_response(("issue-1", 1, 1_000)))]
        )
        assert [request.method for request in result.requests] == ["POST", "POST"]
        assert [row["id"] for row in result.rows] == ["issue-1"]


_SEEDED = dict.fromkeys(DatadogIssueSearchConfig().issue_fields)


class TestJoinIncluded:
    SEARCH = DatadogIssueSearchConfig()

    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            # No ``included`` at all: the row keeps its id and counts.
            (
                {"data": [_issue_result("issue-1", 4)]},
                [
                    {
                        **_SEEDED,
                        "id": "issue-1",
                        "window_total_count": 4,
                        "window_impacted_sessions": 1,
                        "window_impacted_users": 1,
                    }
                ],
            ),
            # No relationship: the result id is the issue id.
            (
                {
                    "data": [{"id": "issue-1", "attributes": {"total_count": 2}}],
                    "included": [_issue_included("issue-1", 5, error_type="TimeoutError")],
                },
                [
                    {
                        **_SEEDED,
                        "id": "issue-1",
                        "error_type": "TimeoutError",
                        "error_message": "Connection refused",
                        "service": "checkout-api",
                        "state": "OPEN",
                        "first_seen": 1_772_593_094_123,
                        "last_seen": 5,
                        "window_total_count": 2,
                        "window_impacted_sessions": None,
                        "window_impacted_users": None,
                    }
                ],
            ),
            # Null attributes on both sides must not raise.
            (
                {
                    "data": [{"id": "issue-1", "attributes": None, "relationships": None}],
                    "included": [{"id": "issue-1", "type": "issue", "attributes": None}],
                },
                [
                    {
                        **_SEEDED,
                        "id": "issue-1",
                        "window_total_count": None,
                        "window_impacted_sessions": None,
                        "window_impacted_users": None,
                    }
                ],
            ),
            # Only issue objects supply attributes; a case or team that reuses the id must not leak in.
            (
                {
                    "data": [_issue_result("issue-1", 1)],
                    "included": [
                        {"id": "issue-1", "type": "case", "attributes": {"title": "Not an issue"}},
                        _issue_included("issue-1", 5, error_type="TimeoutError"),
                    ],
                },
                [
                    {
                        **_SEEDED,
                        "id": "issue-1",
                        "error_type": "TimeoutError",
                        "error_message": "Connection refused",
                        "service": "checkout-api",
                        "state": "OPEN",
                        "first_seen": 1_772_593_094_123,
                        "last_seen": 5,
                        "window_total_count": 1,
                        "window_impacted_sessions": 1,
                        "window_impacted_users": 1,
                    }
                ],
            ),
            ("not a dict", []),
        ],
    )
    def test_join_edge_cases(self, response: Any, expected: Any) -> None:
        assert _join_included(response, self.SEARCH) == expected


class TestEpochMsToIso:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1_772_593_094_123, "2026-03-04T02:58:14.123Z"),
            (1_772_593_094_000, "2026-03-04T02:58:14.000Z"),
            (1_772_593_094_123.0, "2026-03-04T02:58:14.123Z"),
            (None, None),
            ("2026-03-04T02:58:14.123Z", "2026-03-04T02:58:14.123Z"),
            (True, True),
        ],
    )
    def test_epoch_ms_to_iso(self, value: Any, expected: Any) -> None:
        assert _epoch_ms_to_iso(value) == expected
