from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.loops import LoopsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.loops.loops import (
    LoopsResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.loops.settings import LOOPS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.loops.source import LoopsSource


def _page(rows: list[dict[str, Any]], next_cursor: str | None) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "pagination": {
                "totalResults": len(rows),
                "returnedResults": len(rows),
                "perPage": 50,
                "totalPages": 1,
                "nextCursor": next_cursor,
                "nextPage": None,
            },
            "data": rows,
        }
    )


class TestLoopsSource:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(LoopsSource(), LoopsSourceConfig(api_key="test-key"))

    def test_fresh_run_pages_through_cursors_and_saves_state(self) -> None:
        result = self._driver().run(
            "campaigns",
            [
                _page([{"id": "c1"}], next_cursor="cursor-1"),
                _page([{"id": "c2"}], next_cursor="cursor-2"),
                _page([{"id": "c3"}], next_cursor=None),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["c1", "c2", "c3"]
        # First request has no cursor (fresh run); subsequent requests carry the
        # prior page's nextCursor. Every request asks for the max page size.
        assert result.params("cursor") == [None, "cursor-1", "cursor-2"]
        assert result.params("perPage") == ["50", "50", "50"]
        assert result.saved_states == [
            LoopsResumeConfig(cursor="cursor-1"),
            LoopsResumeConfig(cursor="cursor-2"),
        ]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        result = self._driver().run(
            "campaigns",
            [_page([{"id": "c4"}], next_cursor=None)],
            resume_state=LoopsResumeConfig(cursor="cursor-resumed"),
        )

        assert result.raised is None
        assert result.params("cursor") == ["cursor-resumed"]

    @pytest.mark.parametrize(
        ("endpoint", "parent_path", "child_path", "id_column", "unavailable_status"),
        [
            # A campaign that has not been sent yet answers 400.
            ("campaign_metrics", "/api/v1/campaigns", "/api/v1/campaigns/{}/metrics", "campaignId", 400),
            (
                "transactional_email_metrics",
                "/api/v1/transactional-emails",
                "/api/v1/transactional-emails/{}/metrics",
                "transactionalId",
                404,
            ),
        ],
    )
    def test_metrics_fan_out_over_parent_and_skip_unavailable(
        self, endpoint: str, parent_path: str, child_path: str, id_column: str, unavailable_status: int
    ) -> None:
        result = self._driver().run(
            endpoint,
            [
                _page([{"id": "a"}, {"id": "b"}], next_cursor="cursor-1"),
                ScriptedResponse(json={"sends": 10, "hardBounces": 1}),
                ScriptedResponse(status=unavailable_status, json={"message": "unavailable"}),
                _page([{"id": "c"}], next_cursor=None),
                ScriptedResponse(json={"sends": 3, "hardBounces": 0}),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"sends": 10, "hardBounces": 1, id_column: "a"},
            {"sends": 3, "hardBounces": 0, id_column: "c"},
        ]
        assert result.paths == [
            parent_path,
            child_path.format("a"),
            child_path.format("b"),
            parent_path,
            child_path.format("c"),
        ]
        assert result.queries == [
            {"perPage": ("50",)},
            {},
            {},
            {"perPage": ("50",), "cursor": ("cursor-1",)},
            {},
        ]
        assert all(request.origin == "https://app.loops.so" for request in result.requests)
        assert result.saved_states == []

    def test_workflow_node_metrics_fan_out_over_email_nodes(self) -> None:
        email_node = {"typeName": "SendEmailAction", "nextNodeIds": [], "emailMessageId": "m1", "subject": "Hi"}
        result = self._driver().run(
            "workflow_node_metrics",
            [
                _page([{"id": "w1"}, {"id": "w2"}], next_cursor="cursor-1"),
                ScriptedResponse(
                    json={
                        "id": "w1",
                        "nodes": {
                            "t1": {"typeName": "SignupTrigger", "nextNodeIds": ["n1"]},
                            "n1": email_node,
                            "n2": {**email_node, "emailMessageId": None},
                        },
                    }
                ),
                ScriptedResponse(json={"sends": 10, "opens": 4}),
                # A node with no email message answers 400.
                ScriptedResponse(status=400, json={"message": "Node has no email message."}),
                # A workflow deleted after the listing answers 404.
                ScriptedResponse(status=404, json={"message": "Workflow not found."}),
                _page([{"id": "w3"}], next_cursor=None),
                ScriptedResponse(json={"id": "w3", "nodes": {"n3": email_node}}),
                ScriptedResponse(json={"sends": 2, "opens": 1}),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"sends": 10, "opens": 4, "workflowId": "w1", "nodeId": "n1", "emailMessageId": "m1", "subject": "Hi"},
            {"sends": 2, "opens": 1, "workflowId": "w3", "nodeId": "n3", "emailMessageId": "m1", "subject": "Hi"},
        ]
        assert result.paths == [
            "/api/v1/workflows",
            "/api/v1/workflows/w1",
            "/api/v1/workflows/w1/nodes/n1/metrics",
            "/api/v1/workflows/w1/nodes/n2/metrics",
            "/api/v1/workflows/w2",
            "/api/v1/workflows",
            "/api/v1/workflows/w3",
            "/api/v1/workflows/w3/nodes/n3/metrics",
        ]
        assert result.params("cursor")[5] == "cursor-1"

    @pytest.mark.parametrize("endpoint", list(LOOPS_ENDPOINTS.keys()))
    def test_source_response_primary_and_partition_keys(self, endpoint: str) -> None:
        endpoint_config = LOOPS_ENDPOINTS[endpoint]
        if endpoint_config.paginated or endpoint_config.fanout or endpoint_config.per_workflow_node:
            answer = _page([], next_cursor=None)
        else:
            answer = ScriptedResponse(json=[])
        result = self._driver().run(endpoint, [answer])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == list(endpoint_config.primary_keys)
        if endpoint_config.partition_key:
            assert result.response.partition_keys == [endpoint_config.partition_key]
            assert result.response.partition_mode == "datetime"
        else:
            assert result.response.partition_keys is None
            assert result.response.partition_mode is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_message_fragment"),
        [
            (200, True, None),
        ],
    )
    def test_status_code_mapping(
        self, status_code: int, expected_valid: bool, expected_message_fragment: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={"success": True}))) as network:
            is_valid, message = validate_credentials("test-key")

        assert {request.path for request in network.requests_log} == {"/api/v1/api-key"}
        assert network.requests_log[0].headers["authorization"] == "Bearer test-key"
        assert is_valid is expected_valid
        if expected_message_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_message_fragment in message

    def test_network_error_returns_invalid(self) -> None:
        with scripted_network(always(ConnectionError("connection refused"))) as network:
            is_valid, message = validate_credentials("test-key")

        assert {request.path for request in network.requests_log} == {"/api/v1/api-key"}
        assert is_valid is False
        assert message is not None and "connection refused" in message
