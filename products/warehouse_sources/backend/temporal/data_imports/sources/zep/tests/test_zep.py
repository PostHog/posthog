from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zep import ZepSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zep.settings import ZEP_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zep.source import ZepSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zep.zep import (
    ZEP_BASE_URL,
    ZepResumeConfig,
    ZepRetryableError,
    _build_url,
)


def _run(endpoint: str, script: Any, resume_state: ZepResumeConfig | None = None) -> DriveResult:
    driver = SourceDriver(ZepSource(), ZepSourceConfig(api_key="z_test"))
    return driver.run(endpoint, script, resume_state=resume_state)


class TestHelpers:
    def test_build_url_no_params(self) -> None:
        assert _build_url("/threads", {}) == f"{ZEP_BASE_URL}/threads"


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_statuses_retry_then_succeed(self, _name: str, status_code: int) -> None:
        result = _run(
            "users",
            [ScriptedResponse(status=status_code, json={}), ScriptedResponse(json={"users": []})],
        )

        assert result.raised is None
        assert result.rows == []
        assert result.paths == ["/api/v2/users-ordered", "/api/v2/users-ordered"]

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_persistent_retryable_status_raises_retryable_error(self, _name: str, status_code: int) -> None:
        result = _run("users", always(ScriptedResponse(status=status_code, json={})))

        assert isinstance(result.raised, ZepRetryableError)

    def test_client_error_raises_immediately(self) -> None:
        result = _run("users", [ScriptedResponse(status=401, json={"message": "unauthorized"})])

        assert isinstance(result.raised, requests.HTTPError)
        # A 4xx is a permanent failure: no retry.
        assert result.paths == ["/api/v2/users-ordered"]


class TestPageBasedPagination:
    def test_stops_on_short_page_and_injects_nothing(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(ZEP_ENDPOINTS["users"], "page_size", 2)
        result = _run(
            "users",
            [
                ScriptedResponse(json={"users": [{"uuid": "u1"}, {"uuid": "u2"}], "total_count": 3}),
                ScriptedResponse(json={"users": [{"uuid": "u3"}], "total_count": 3}),
            ],
        )

        assert [r["uuid"] for r in result.rows] == ["u1", "u2", "u3"]
        # First page requested pageNumber=1; state saved pointing at page 2 after yielding page 1.
        assert result.params("pageNumber")[0] == "1"
        assert result.saved_states == [ZepResumeConfig(page_number=2)]


class TestThreadMessagesFanOut:
    @staticmethod
    def _threads(*thread_ids: str) -> ScriptedResponse:
        return ScriptedResponse(
            json={"threads": [{"thread_id": thread_id} for thread_id in thread_ids], "total_count": len(thread_ids)}
        )

    def test_fans_out_over_threads_and_injects_parent_ids(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(ZEP_ENDPOINTS["thread_messages"], "page_size", 2)
        result = _run(
            "thread_messages",
            route(
                {
                    "/threads": [self._threads("T1", "T2")],
                    "/threads/T1/messages": [
                        ScriptedResponse(json={"messages": [{"uuid": "m1"}], "total_count": 1, "user_id": "U1"})
                    ],
                    "/threads/T2/messages": [
                        ScriptedResponse(json={"messages": [{"uuid": "m2"}], "total_count": 1, "user_id": "U2"})
                    ],
                }
            ),
        )

        assert result.rows == [
            {"uuid": "m1", "thread_id": "T1", "user_id": "U1"},
            {"uuid": "m2", "thread_id": "T2", "user_id": "U2"},
        ]

    def test_resumes_from_saved_thread(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(ZEP_ENDPOINTS["thread_messages"], "page_size", 2)
        result = _run(
            "thread_messages",
            route(
                {
                    "/threads": [self._threads("T1", "T2")],
                    "/threads/T2/messages": [
                        ScriptedResponse(json={"messages": [{"uuid": "m2"}], "total_count": 1, "user_id": "U2"})
                    ],
                }
            ),
            resume_state=ZepResumeConfig(thread_id="T2", cursor=0),
        )

        # T1 is skipped: we resume straight into T2.
        assert [r["uuid"] for r in result.rows] == ["m2"]
        message_paths = [path for path in result.paths if path.endswith("/messages")]
        assert message_paths == ["/api/v2/threads/T2/messages"]

    def test_cursor_advances_across_message_pages(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(ZEP_ENDPOINTS["thread_messages"], "page_size", 2)
        result = _run(
            "thread_messages",
            route(
                {
                    "/threads": [self._threads("T1")],
                    "/threads/T1/messages": [
                        ScriptedResponse(
                            json={"messages": [{"uuid": "m1"}, {"uuid": "m2"}], "total_count": 3, "user_id": "U1"}
                        ),
                        ScriptedResponse(json={"messages": [{"uuid": "m3"}], "total_count": 3, "user_id": "U1"}),
                    ],
                }
            ),
        )

        assert [r["uuid"] for r in result.rows] == ["m1", "m2", "m3"]
        # Second page requested with cursor advanced past the first two messages.
        message_requests = [request for request in result.requests if request.path.endswith("/messages")]
        assert message_requests[1].param("cursor") == "2"
        assert result.saved_states == [ZepResumeConfig(thread_id="T1", cursor=2)]


class TestGraphFanOut:
    @staticmethod
    def _owners(users: list[str], graphs: list[str]) -> dict[str, list[ScriptedResponse]]:
        return {
            "/users-ordered": [
                ScriptedResponse(json={"users": [{"user_id": u} for u in users], "total_count": len(users)})
            ],
            "/graph/list-all": [
                ScriptedResponse(json={"graphs": [{"graph_id": g} for g in graphs], "total_count": len(graphs)})
            ],
        }

    @parameterized.expand(
        [
            ("graph_edges", "edge", 100),
            ("graph_nodes", "node", 100),
            ("graph_episodes", "episodes", 50),
        ]
    )
    def test_walks_user_and_standalone_graphs_by_cursor_header(self, endpoint: str, kind: str, limit: int) -> None:
        result = _run(
            endpoint,
            route(
                {
                    **self._owners(["U1"], ["G1"]),
                    f"/graph/{kind}/user/U1": [
                        ScriptedResponse(json=[{"uuid": "a"}], headers={"Zep-Next-Cursor": "c1"}),
                        ScriptedResponse(json=[{"uuid": "b"}]),
                    ],
                    f"/graph/{kind}/graph/G1": [ScriptedResponse(json=[{"uuid": "c"}])],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {"uuid": "a", "graph_scope": "user", "graph_owner_id": "U1", "user_id": "U1", "graph_id": None},
            {"uuid": "b", "graph_scope": "user", "graph_owner_id": "U1", "user_id": "U1", "graph_id": None},
            {"uuid": "c", "graph_scope": "graph", "graph_owner_id": "G1", "user_id": None, "graph_id": "G1"},
        ]
        graph_requests = [r for r in result.requests if r.path.startswith(f"/api/v2/graph/{kind}/")]
        assert [r.method for r in graph_requests] == ["POST", "POST", "POST"]
        assert [r.json() for r in graph_requests] == [
            {"limit": limit, "order_by": "created_at", "direction": "asc"},
            {"limit": limit, "order_by": "created_at", "direction": "asc", "cursor": "c1"},
            {"limit": limit, "order_by": "created_at", "direction": "asc"},
        ]
        # Each cursor is staged before the page it follows is yielded.
        assert result.saved_states == [
            ZepResumeConfig(graph_scope="user", graph_owner_id="U1", graph_cursor="c1"),
            ZepResumeConfig(graph_scope="graph", graph_owner_id="G1"),
            ZepResumeConfig(graph_finished=True),
        ]

    @parameterized.expand(
        [
            ("deleted_graph", ScriptedResponse(status=404, json={"message": "not found"})),
            ("empty_graph", ScriptedResponse(json=[])),
            ("null_body", ScriptedResponse(body=b"null")),
        ]
    )
    def test_graph_without_rows_moves_on_to_next_graph(self, _name: str, first_answer: ScriptedResponse) -> None:
        result = _run(
            "graph_edges",
            route(
                {
                    **self._owners(["U1", "U2"], []),
                    "/graph/edge/user/U1": [first_answer],
                    "/graph/edge/user/U2": [ScriptedResponse(json=[{"uuid": "e2"}])],
                }
            ),
        )

        assert result.raised is None
        assert [r["uuid"] for r in result.rows] == ["e2"]
        assert result.committed_states[0] == ZepResumeConfig(graph_scope="user", graph_owner_id="U2")

    def test_repeated_cursor_ends_the_graph(self) -> None:
        result = _run(
            "graph_nodes",
            route(
                {
                    **self._owners(["U1"], []),
                    "/graph/node/user/U1": [
                        ScriptedResponse(json=[{"uuid": "n1"}], headers={"Zep-Next-Cursor": "c1"}),
                        ScriptedResponse(json=[{"uuid": "n2"}], headers={"Zep-Next-Cursor": "c1"}),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [r["uuid"] for r in result.rows] == ["n1", "n2"]

    def test_resumes_from_saved_graph_and_cursor(self) -> None:
        result = _run(
            "graph_episodes",
            route(
                {
                    **self._owners(["U1"], ["G1", "G2"]),
                    "/graph/episodes/graph/G1": [ScriptedResponse(json=[{"uuid": "ep2"}])],
                    "/graph/episodes/graph/G2": [ScriptedResponse(json=[{"uuid": "ep3"}])],
                }
            ),
            resume_state=ZepResumeConfig(graph_scope="graph", graph_owner_id="G1", graph_cursor="c9"),
        )

        assert [r["uuid"] for r in result.rows] == ["ep2", "ep3"]
        graph_requests = [r for r in result.requests if r.path.startswith("/api/v2/graph/episodes/")]
        assert [r.path for r in graph_requests] == [
            "/api/v2/graph/episodes/graph/G1",
            "/api/v2/graph/episodes/graph/G2",
        ]
        assert graph_requests[0].json()["cursor"] == "c9"
        assert "cursor" not in graph_requests[1].json()

    def test_resume_into_vanished_graph_ends_cleanly(self) -> None:
        result = _run(
            "graph_edges",
            route(self._owners(["U1"], [])),
            resume_state=ZepResumeConfig(graph_scope="graph", graph_owner_id="gone"),
        )

        assert result.raised is None
        assert result.rows == []

    def test_resume_after_last_graph_reads_nothing_again(self) -> None:
        result = _run(
            "graph_edges",
            route(self._owners(["U1"], [])),
            resume_state=ZepResumeConfig(graph_finished=True),
        )

        assert result.raised is None
        assert result.rows == []
        assert result.requests == []


class TestZepSourceResponse:
    @parameterized.expand(
        [
            ("users", ["uuid"], "asc"),
            ("threads", ["uuid"], "asc"),
            ("thread_messages", ["uuid"], "asc"),
            ("graphs", ["uuid"], "asc"),
            ("graph_edges", ["graph_scope", "graph_owner_id", "uuid"], None),
            ("graph_nodes", ["graph_scope", "graph_owner_id", "uuid"], None),
            ("graph_episodes", ["graph_scope", "graph_owner_id", "uuid"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, expected_pks: list[str], expected_sort: str | None) -> None:
        result = _run(endpoint, always(ScriptedResponse(json={"users": [], "threads": [], "graphs": []})))

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        assert response.sort_mode == expected_sort
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
