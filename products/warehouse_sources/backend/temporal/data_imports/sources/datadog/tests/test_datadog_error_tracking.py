import dataclasses
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.datadog import datadog as ddog
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


class TestErrorTablesOptIn:
    def test_error_tables_are_opt_in(self) -> None:
        config = DatadogSourceConfig(api_key="dd-api", application_key="dd-app", site="datadoghq.com")
        schemas = {s.name: s for s in DatadogSource().get_schemas(config, 123)}
        for name in ("error_tracking_issues", "error_spans", "error_logs"):
            assert schemas[name].should_sync_default is False
        assert schemas["logs"].should_sync_default is True


class TestWalkPageCap:
    def test_max_pages_per_sync_stops_the_walk(self) -> None:
        # The error endpoints are rate limited, so a sync stops after a bounded number of pages and the
        # next one continues from the checkpointed cursor value.
        capped = dataclasses.replace(DATADOG_ENDPOINTS["error_logs"], max_pages_per_sync=2)
        bodies = [
            {"data": [{"id": str(i), "attributes": {}}], "links": {"next": f"https://api.datadoghq.com/p{i + 1}"}}
            for i in range(4)
        ]
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        manager.load_state.return_value = None
        fetched: list[str] = []
        logger = mock.MagicMock()

        def fake_get(url: str, timeout: Any = None) -> Any:
            resp = mock.MagicMock()
            resp.status_code = 200
            resp.ok = True
            resp.json.return_value = bodies[len(fetched)]
            fetched.append(url)
            return resp

        with (
            mock.patch.dict(DATADOG_ENDPOINTS, {"error_logs": capped}),
            mock.patch.object(ddog, "make_tracked_session") as mock_session,
        ):
            mock_session.return_value.get.side_effect = fake_get
            rows = list(
                ddog.get_rows(
                    site="datadoghq.com",
                    api_key="api",
                    app_key="app",
                    endpoint="error_logs",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert len(fetched) == 2
        assert [batch[0]["id"] for batch in rows] == ["0", "1"]
        logger.warning.assert_called_once()
        assert logger.warning.call_args.args == ("datadog.page_cap_reached",)


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
    def _run(self, responses: list[Any], config_override: Any = None) -> dict[str, Any]:
        """Run the issue sync against queued responses. An int is a bare HTTP status."""
        manager = mock.MagicMock()
        calls: list[dict[str, Any]] = []
        logger = mock.MagicMock()

        def fake_post(url: str, json: Any = None, timeout: Any = None) -> Any:
            calls.append({"url": url, "body": json})
            queued = responses[min(len(calls), len(responses)) - 1]
            resp = mock.MagicMock()
            resp.status_code = queued if isinstance(queued, int) else 200
            resp.ok = resp.status_code < 400
            resp.text = f"{resp.status_code} body"
            resp.json.return_value = {} if isinstance(queued, int) else queued
            if not resp.ok:
                resp.raise_for_status.side_effect = requests.HTTPError(
                    f"{resp.status_code} Client Error", response=resp
                )
            return resp

        endpoint_patch = {"error_tracking_issues": config_override} if config_override else {}
        with (
            mock.patch.dict(DATADOG_ENDPOINTS, endpoint_patch),
            mock.patch.object(ddog, "make_tracked_session") as mock_session,
            mock.patch("tenacity.nap.time.sleep"),
        ):
            mock_session.return_value.post.side_effect = fake_post
            rows = [
                row
                for batch in ddog.get_rows(
                    site="datadoghq.com",
                    api_key="api",
                    app_key="app",
                    endpoint="error_tracking_issues",
                    logger=logger,
                    resumable_source_manager=manager,
                )
                for row in batch
            ]
            get_called = mock_session.return_value.get.called

        return {"rows": rows, "calls": calls, "logger": logger, "get_called": get_called, "manager": manager}

    @staticmethod
    def _with_search(**overrides: Any) -> Any:
        base = DATADOG_ENDPOINTS["error_tracking_issues"]
        assert base.search is not None
        return dataclasses.replace(base, search=dataclasses.replace(base.search, **overrides))

    def test_posts_a_search_body_and_shapes_rows(self) -> None:
        result = self._run([_issue_response(("issue-1", 12, 1_772_679_494_000))])

        assert not result["get_called"]
        assert len(result["calls"]) == 1
        call = result["calls"][0]
        assert call["url"] == "https://api.datadoghq.com/api/v2/error-tracking/issues/search?include=issue"
        data = call["body"]["data"]
        assert data["type"] == "search_request"
        attributes = data["attributes"]
        assert isinstance(attributes["from"], int)
        assert isinstance(attributes["to"], int)
        assert attributes["from"] < attributes["to"]

        # Attributes the response omits are still present, so the table keeps the same columns.
        assert result["rows"] == [
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
        result["manager"].save_state.assert_not_called()

    def test_full_response_halves_the_window_and_merges_by_issue(self) -> None:
        override = self._with_search(max_results_per_request=3)
        result = self._run(
            [
                # The whole window comes back full, so it may hide issues.
                _issue_response(("issue-1", 1, 1_000), ("issue-2", 1, 1_000), ("issue-3", 1, 1_000)),
                {
                    "data": [_issue_result("issue-1", 3, users=5), _issue_result("issue-2", 5)],
                    "included": [_issue_included("issue-1", 1_000), _issue_included("issue-2", 2_000)],
                },
                {
                    "data": [_issue_result("issue-1", 4, users=2)],
                    "included": [_issue_included("issue-1", 9_000)],
                },
            ],
            config_override=override,
        )

        whole, first, second = (call["body"]["data"]["attributes"] for call in result["calls"])
        assert len(result["calls"]) == 3
        # Earlier half first, and the halves tile the window with no gap or overlap.
        assert first["from"] == whole["from"]
        assert first["to"] == second["from"]
        assert second["to"] == whole["to"]

        by_id = {row["id"]: row for row in result["rows"]}
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
        result = self._run(
            [_issue_response(("issue-1", 1, 1_000), ("issue-2", 2, 1_000))],
            config_override=override,
        )

        assert len(result["calls"]) == 1
        assert {row["id"] for row in result["rows"]} == {"issue-1", "issue-2"}
        result["logger"].warning.assert_called_once()
        assert result["logger"].warning.call_args.args == ("datadog.search_window_truncated",)
        assert result["logger"].warning.call_args.kwargs["max_results"] == 2

    def test_request_cap_stops_splitting_and_warns(self) -> None:
        # Every response is full, so an unbounded sync would split down to the smallest window.
        override = self._with_search(max_results_per_request=1, max_requests_per_sync=5)
        result = self._run([_issue_response(("issue-1", 1, 1_000))], config_override=override)

        assert len(result["calls"]) <= 5
        assert {row["id"] for row in result["rows"]} == {"issue-1"}
        capped = [
            call
            for call in result["logger"].warning.call_args_list
            if call.args == ("datadog.search_request_cap_reached",)
        ]
        assert capped
        assert capped[0].kwargs["max_requests"] == 5

    def test_transient_status_is_retried_on_post(self) -> None:
        # The transport retries only GET, so the POST search depends on the retry in fetch_page.
        result = self._run([503, _issue_response(("issue-1", 1, 1_000))])
        assert len(result["calls"]) == 2
        assert [row["id"] for row in result["rows"]] == ["issue-1"]


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
