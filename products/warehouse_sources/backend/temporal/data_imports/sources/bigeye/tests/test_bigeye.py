import json
from typing import Any, cast

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.bigeye import bigeye as bigeye_module
from products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.bigeye import (
    BigeyeResumeConfig,
    _auth_header_value,
    bigeye_source,
    get_resource,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.settings import REQUEST_TIMEOUT_SECONDS
from products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.source import BigeyeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bigeye import BigeyeSourceConfig

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: BigeyeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request AT PREPARE TIME.

    ``request.params`` / ``request.json`` are single dicts mutated in place across pages, so
    inspecting them after the run shows only the final state — snapshot copies when each request
    is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append(
            {
                "method": request.method,
                "url": request.url,
                "params": dict(request.params or {}),
                "json": dict(request.json) if request.json is not None else None,
            }
        )
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _build(endpoint: str, manager: mock.MagicMock, host: str | None = None, workspace_id: int | None = None) -> Any:
    return bigeye_source(
        api_key="key",
        host=host,
        workspace_id=workspace_id,
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _driver(host: str | None = None, workspace_id: int | None = None) -> SourceDriver:
    return SourceDriver(BigeyeSource(), BigeyeSourceConfig(api_key="key", host=host, workspace_id=workspace_id))


class TestNormalizeHost:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, "app.bigeye.com"),
            ("", "app.bigeye.com"),
            ("   ", "app.bigeye.com"),
            ("app.bigeye.com", "app.bigeye.com"),
            ("https://app.bigeye.com", "app.bigeye.com"),
            ("https://app.bigeye.com/", "app.bigeye.com"),
            ("http://bigeye.internal.example.com/api", "bigeye.internal.example.com"),
        ],
    )
    def test_normalizes(self, value: str | None, expected: str) -> None:
        assert normalize_host(value) == expected


class TestGetResource:
    def test_paginated_endpoint_includes_workspace_id_when_set(self) -> None:
        resource = cast(dict[str, Any], get_resource("Sources", workspace_id=7))
        assert resource["endpoint"]["json"] == {"pageSize": 100, "workspaceId": 7}

    def test_collections_includes_workspace_id_as_query_param(self) -> None:
        resource = cast(dict[str, Any], get_resource("Collections", workspace_id=7))
        assert resource["endpoint"]["params"] == {"workspaceId": 7}


class TestSinglePageEndpoints:
    def test_metrics_uses_metrics_key(self) -> None:
        result = _driver().run("Metrics", [ScriptedResponse(json={"metrics": [{"id": 5}]})])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [5]

    @pytest.mark.parametrize(
        ("endpoint", "body"),
        [
            ("Collections", {"collectionInfos": [{"collectionConfiguration": {"id": 9, "name": "Nightly"}}]}),
            (
                "Deltas",
                {"deltaInfos": [{"delta": {"id": 9, "name": "Nightly"}}], "paginationInfo": {"nextCursor": ""}},
            ),
        ],
    )
    def test_flattens_nested_id(self, endpoint: str, body: dict[str, Any]) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.rows[0]["id"] == 9
        assert result.rows[0]["name"] == "Nightly"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_bounds_every_request_with_a_timeout(self, MockSession: mock.MagicMock) -> None:
        # Without this a stalled connect or hung read on a customer-controlled host would pin an
        # import worker indefinitely.
        session = MockSession.return_value
        manager = _make_manager()
        _wire(session, [_response({"workspaces": [{"id": 1, "name": "Default"}]})])

        _rows(_build("Workspaces", manager))

        assert session.send.call_args.kwargs["timeout"] == REQUEST_TIMEOUT_SECONDS

    def test_client_never_follows_redirects(self) -> None:
        # A validated host could still 3xx a sync request to an internal address; refuse to
        # follow redirects on every sync request (SSRF defense-in-depth).
        result = _driver().run(
            "Workspaces",
            [ScriptedResponse(status=302, headers={"Location": "https://10.0.0.1/internal"})],
        )

        assert len(result.requests) == 1
        assert result.paths == ["/api/v1/workspaces"]
        assert isinstance(result.raised, ValueError)
        assert "refusing to follow" in str(result.raised)


class TestCursorPagination:
    def test_pages_until_cursor_empty(self) -> None:
        result = _driver().run(
            "Sources",
            [
                ScriptedResponse(json={"sources": [{"id": 1}], "paginationInfo": {"nextCursor": "c1"}}),
                ScriptedResponse(json={"sources": [{"id": 2}], "paginationInfo": {"nextCursor": ""}}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2]
        assert [request.method for request in result.requests] == ["POST", "POST"]
        assert result.requests[0].json() == {"pageSize": 100}
        assert result.requests[1].json() == {"pageSize": 100, "pageCursor": "c1"}

    def test_issues_uses_singular_issue_key(self) -> None:
        result = _driver().run(
            "Issues", [ScriptedResponse(json={"issue": [{"id": 3}], "paginationInfo": {"nextCursor": ""}})]
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [3]

    def test_saves_cursor_after_non_terminal_page(self) -> None:
        result = _driver().run(
            "Tables",
            [
                ScriptedResponse(json={"tables": [{"id": 1}], "paginationInfo": {"nextCursor": "c1"}}),
                ScriptedResponse(json={"tables": [{"id": 2}], "paginationInfo": {"nextCursor": ""}}),
            ],
        )

        assert result.raised is None
        assert result.saved_states == [BigeyeResumeConfig(next_cursor="c1")]

    def test_resume_seeds_cursor(self) -> None:
        result = _driver().run(
            "Tables",
            [ScriptedResponse(json={"tables": [{"id": 1}], "paginationInfo": {"nextCursor": ""}})],
            resume_state=BigeyeResumeConfig(next_cursor="resumed"),
        )

        assert result.raised is None
        assert result.requests[0].json() == {"pageSize": 100, "pageCursor": "resumed"}


class TestPerMetricEndpoints:
    def test_metric_runs_walk_each_metric_and_stage_the_next_position(self) -> None:
        result = _driver(workspace_id=7).run(
            "MetricRuns",
            [
                ScriptedResponse(json={"metrics": [{"id": 2}, {"id": 1}]}),
                ScriptedResponse(json={"metricRuns": [{"id": 10}], "paginationInfo": {"nextCursor": "c1"}}),
                ScriptedResponse(json={"metricRuns": [{"id": 11}], "paginationInfo": {"nextCursor": ""}}),
                ScriptedResponse(json={"metricRuns": [{"id": 20}], "paginationInfo": {"nextCursor": ""}}),
            ],
        )

        assert result.raised is None
        assert [(row["metric_id"], row["id"]) for row in result.rows] == [(1, 10), (1, 11), (2, 20)]
        assert result.paths == ["/api/v1/metrics"] + ["/api/v1/metrics/runs"] * 3
        assert all(request.headers.get("x-bigeye-workspace-id") == "7" for request in result.requests)
        assert [request.json() for request in result.requests[1:]] == [
            {"metricIdentifier": {"metricId": 1}, "pageSize": 100},
            {"metricIdentifier": {"metricId": 1}, "pageSize": 100, "pageCursor": "c1"},
            {"metricIdentifier": {"metricId": 2}, "pageSize": 100},
        ]
        assert result.saved_states == [
            BigeyeResumeConfig(next_cursor="c1", metric_id=1),
            BigeyeResumeConfig(next_cursor="", metric_id=2),
        ]

    @pytest.mark.parametrize(
        ("listed_metric_ids", "expected_body"),
        [
            ([1, 2, 3], {"metricIdentifier": {"metricId": 2}, "pageSize": 100, "pageCursor": "r"}),
            # The saved metric was deleted: resume at the next id, without its stale cursor.
            ([1, 3], {"metricIdentifier": {"metricId": 3}, "pageSize": 100}),
        ],
    )
    def test_metric_runs_resume_from_saved_metric(
        self, listed_metric_ids: list[int], expected_body: dict[str, Any]
    ) -> None:
        result = _driver().run(
            "MetricRuns",
            [
                ScriptedResponse(json={"metrics": [{"id": metric_id} for metric_id in listed_metric_ids]}),
                ScriptedResponse(json={"metricRuns": [{"id": 21}], "paginationInfo": {"nextCursor": ""}}),
                ScriptedResponse(json={"metricRuns": [], "paginationInfo": {"nextCursor": ""}}),
            ],
            resume_state=BigeyeResumeConfig(next_cursor="r", metric_id=2),
        )

        assert result.raised is None
        assert result.requests[1].json() == expected_body

    def test_metric_revisions_flatten_revision_info_and_skip_deleted_metrics(self) -> None:
        result = _driver().run(
            "MetricRevisions",
            [
                ScriptedResponse(json={"metrics": [{"id": 1}, {"id": 2}]}),
                ScriptedResponse(status=404, json={"message": "metric not found"}),
                ScriptedResponse(
                    json={
                        "revisions": [
                            {
                                "metric": {"id": 2},
                                "revisionInfo": {"epochSeconds": "1700000000", "type": "REVISION_TYPE_UPDATE"},
                            }
                        ]
                    }
                ),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/metrics", "/api/v1/metrics/1/revisions", "/api/v1/metrics/2/revisions"]
        assert [(row["metric_id"], row["revision_epoch_seconds"], row["revision_type"]) for row in result.rows] == [
            (2, "1700000000", "REVISION_TYPE_UPDATE")
        ]


def _lineage_graph(*node_ids: int) -> dict[str, Any]:
    return {
        "nodes": {
            str(node_id): {"lineageNode": {"id": node_id, "nodeName": f"node_{node_id}"}, "issueCount": 0}
            for node_id in node_ids
        }
    }


class TestLineageGraph:
    def test_walks_each_table_data_node_and_stages_the_next_node(self) -> None:
        result = _driver(workspace_id=7).run(
            "LineageGraph",
            [
                ScriptedResponse(
                    json={
                        # A table with no data node has no lineage and gets no graph request.
                        "tables": [{"id": 1, "dataNodeId": 30}, {"id": 2}],
                        "paginationInfo": {"nextCursor": "c1"},
                    }
                ),
                ScriptedResponse(json={"tables": [{"id": 3, "dataNodeId": 10}], "paginationInfo": {"nextCursor": ""}}),
                ScriptedResponse(json=_lineage_graph(10, 11)),
                ScriptedResponse(json=_lineage_graph(30, 10)),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/tables/fetch"] * 2 + [
            "/api/v2/lineage/nodes/10/graph",
            "/api/v2/lineage/nodes/30/graph",
        ]
        assert [request.json() for request in result.requests[:2]] == [
            {"pageSize": 100, "includeDataNodeIds": True, "ignoreFields": True, "workspaceId": 7},
            {"pageSize": 100, "includeDataNodeIds": True, "ignoreFields": True, "workspaceId": 7, "pageCursor": "c1"},
        ]
        assert result.queries[2:] == [{"depth": ("1",), "direction": ("ALL",)}] * 2
        assert all(request.headers.get("x-bigeye-workspace-id") == "7" for request in result.requests)
        assert [(row["root_data_node_id"], row["id"], row["node_name"]) for row in result.rows] == [
            (10, 10, "node_10"),
            (10, 11, "node_11"),
            (30, 30, "node_30"),
            (30, 10, "node_10"),
        ]
        assert result.saved_states == [BigeyeResumeConfig(next_cursor="", data_node_id=30)]

    @pytest.mark.parametrize(
        ("listed_node_ids", "expected_path"),
        [
            ([10, 20, 30], "/api/v2/lineage/nodes/20/graph"),
            # The saved node is gone: resume at the next node id.
            ([10, 30], "/api/v2/lineage/nodes/30/graph"),
        ],
    )
    def test_resumes_from_saved_node(self, listed_node_ids: list[int], expected_path: str) -> None:
        result = _driver().run(
            "LineageGraph",
            [
                ScriptedResponse(
                    json={
                        "tables": [{"id": node_id, "dataNodeId": node_id} for node_id in listed_node_ids],
                        "paginationInfo": {"nextCursor": ""},
                    }
                ),
                ScriptedResponse(json=_lineage_graph(1)),
                ScriptedResponse(json=_lineage_graph(2)),
            ],
            resume_state=BigeyeResumeConfig(next_cursor="", data_node_id=20),
        )

        assert result.raised is None
        assert result.paths[1] == expected_path

    @pytest.mark.parametrize(
        "graph_response",
        [
            ScriptedResponse(status=404, json={"message": "data node not found"}),
            # An empty graph omits the `nodes` map.
            ScriptedResponse(json={}),
        ],
    )
    def test_skips_missing_or_empty_graphs(self, graph_response: ScriptedResponse) -> None:
        result = _driver().run(
            "LineageGraph",
            [
                ScriptedResponse(
                    json={
                        "tables": [{"id": 1, "dataNodeId": 10}, {"id": 2, "dataNodeId": 20}],
                        "paginationInfo": {"nextCursor": ""},
                    }
                ),
                graph_response,
                ScriptedResponse(json=_lineage_graph(20)),
            ],
        )

        assert result.raised is None
        assert [(row["root_data_node_id"], row["id"]) for row in result.rows] == [(20, 20)]


class TestMetricScorecard:
    def test_explodes_daily_counts_per_category(self) -> None:
        result = _driver(workspace_id=7).run(
            "MetricScorecard",
            [
                ScriptedResponse(
                    json={
                        "scorecards": [
                            {
                                "metricCategory": "METRIC_CATEGORY_COMPLETENESS",
                                "metricRunCounts": [
                                    {"runAtMinute": "1700000000", "truePositiveIssuesOpened": 2},
                                    {"runAtMinute": "1700086400", "truePositiveIssuesOpened": 0},
                                ],
                            },
                            {"metricCategory": "METRIC_CATEGORY_VALIDITY"},
                        ]
                    }
                )
            ],
        )

        assert result.raised is None
        assert result.requests[0].json() == {"daysOfHistory": 90, "where": {"workspaceId": 7}}
        assert [(row["metric_category"], row["run_at_epoch_seconds"]) for row in result.rows] == [
            ("METRIC_CATEGORY_COMPLETENESS", "1700000000"),
            ("METRIC_CATEGORY_COMPLETENESS", "1700086400"),
        ]


class TestBigeyeSourceResponse:
    def test_auth_header_carries_apikey_prefix(self) -> None:
        # Bigeye's auth header is `apikey <token>`, not the framework's default `Bearer <token>`.
        assert _auth_header_value("secret-token") == "apikey secret-token"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status", "expected_error"),
        [
            (401, "Invalid Bigeye API key. Please check your key and try again."),
        ],
    )
    def test_rejected_status(self, status: int, expected_error: str) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            valid, error = validate_credentials(api_key="key", host=None, workspace_id=None)

        assert valid is False
        assert error is not None and expected_error in error
        if status == 401:
            assert error == expected_error
        assert network.requests_log[0].path == "/api/v1/workspaces"

    def test_rejects_redirect_response(self) -> None:
        # A validated host that 3xx-redirects (potentially to an internal address) must be
        # rejected, not followed (SSRF).
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://10.0.0.1/internal"})]
        ) as network:
            valid, error = validate_credentials(api_key="key", host=None, workspace_id=None)

        assert valid is False
        assert error == "That Bigeye host is not allowed."
        assert len(network.requests_log) == 1

    def test_blocks_unsafe_host_when_team_id_supplied(self) -> None:
        # When a team_id is supplied, a host resolving to an internal address is rejected before
        # any HTTP request is made (SSRF guard).
        with (
            mock.patch.object(bigeye_module, "_is_host_safe", return_value=(False, "internal address")),
            scripted_network([]) as network,
        ):
            valid, error = validate_credentials(api_key="key", host="10.0.0.1", workspace_id=None, team_id=99)

        assert valid is False
        assert error == "internal address"
        assert network.requests_log == []

    def test_custom_host_is_used(self) -> None:
        with scripted_network([ScriptedResponse(json={"workspaces": []})]) as network:
            validate_credentials(api_key="key", host="bigeye.internal.example.com", workspace_id=None)

        assert network.requests_log[0].url == "https://bigeye.internal.example.com/api/v1/workspaces"
