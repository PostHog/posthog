from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.sources.spot_io._config import SpotIoSourceConfig
from products.warehouse_sources.sources.spot_io.source import SpotIoSource
from products.warehouse_sources.sources.spot_io.spot_io import (
    SpotIoResumeConfig,
    _account_params,
    get_resource,
    validate_credentials,
)


def _items(*items: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json={"response": {"items": list(items)}})


def _run(
    endpoint: str,
    script: list[ScriptedResponse],
    resume_state: SpotIoResumeConfig | None = None,
    account_id: str | None = None,
    **inputs: Any,
) -> DriveResult:
    config = SpotIoSourceConfig(api_token="token", account_id=account_id)
    return SourceDriver(SpotIoSource(), config).run(endpoint, script, resume_state=resume_state, **inputs)


class TestSpotIoAccountParams:
    @parameterized.expand(
        [
            ("with_account", "act-123", {"accountId": "act-123"}),
            ("no_account", None, {}),
            ("empty_string", "", {}),
        ]
    )
    def test_account_params(self, _name, account_id, expected) -> None:
        assert _account_params(account_id) == expected


class TestSpotIoGetResource:
    def test_rejects_fanout_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource(endpoint="elastigroup_costs")


class TestSpotIoValidateCredentials:
    @parameterized.expand(
        [
            (200, True, None),
        ]
    )
    def test_validate_credentials_status_mapping(self, status, expected_valid, expected_message) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            result = validate_credentials(api_token="token")

        assert result == (expected_valid, expected_message)
        request = network.requests_log[0]
        assert request.url == "https://api.spotinst.io/aws/ec2/group"
        assert request.headers["authorization"] == "Bearer token"


class TestSpotIoSourceTopLevel:
    def test_unpaginated_endpoint_saves_no_checkpoint(self) -> None:
        result = _run("elastigroups", [_items({"id": "g1"}, {"id": "g2"})])

        assert result.rows == [{"id": "g1"}, {"id": "g2"}]
        assert len(result.requests) == 1
        assert result.saved_states == []

    @parameterized.expand(
        [
            ("account_scoped", "elastigroups", {"accountId": ("act-1",)}),
            ("organization_level", "accounts", {}),
        ]
    )
    def test_account_filter(self, _name, endpoint, expected_query) -> None:
        result = _run(endpoint, [_items({"accountId": "act-1"})], account_id="act-1")

        assert dict(result.requests[0].query) == expected_query


class TestSpotIoFanoutWiring:
    FANOUT_SCRIPT = [
        _items({"id": "g1", "name": "n1"}, {"id": "g2", "name": "n2"}),
        _items({"groupId": "g1", "instanceId": "i1"}),
        _items({"groupId": "g2", "instanceId": "i2"}),
    ]

    def test_fanout_wiring(self) -> None:
        result = _run("elastigroup_costs", self.FANOUT_SCRIPT, account_id="act-1")

        assert result.rows == [
            {"groupId": "g1", "instanceId": "i1", "elastigroup_name": "n1"},
            {"groupId": "g2", "instanceId": "i2", "elastigroup_name": "n2"},
        ]
        # Single-page paginators: one parent request, then one request per group.
        assert result.paths == [
            "/aws/ec2/group",
            "/aws/ec2/group/g1/costs/detailed",
            "/aws/ec2/group/g2/costs/detailed",
        ]
        parent, *children = result.requests
        assert dict(parent.query) == {"accountId": ("act-1",)}
        for child in children:
            assert child.param("fromDate") is not None
            assert child.param("toDate") is not None
            assert child.param("accountId") == "act-1"
        assert [state.paginator_state["completed"] for state in result.saved_states] == [
            ["/aws/ec2/group/g1/costs/detailed"],
            ["/aws/ec2/group/g1/costs/detailed", "/aws/ec2/group/g2/costs/detailed"],
        ]

    def test_resume_skips_completed_groups(self) -> None:
        completed = {"completed": ["/aws/ec2/group/g1/costs/detailed"], "current": None, "child_state": None}

        result = _run(
            "elastigroup_costs",
            [self.FANOUT_SCRIPT[0], self.FANOUT_SCRIPT[2]],
            resume_state=SpotIoResumeConfig(paginator_state=completed),
            account_id="act-1",
        )

        assert result.paths == ["/aws/ec2/group", "/aws/ec2/group/g2/costs/detailed"]
        assert result.rows == [{"groupId": "g2", "instanceId": "i2", "elastigroup_name": "n2"}]


class TestSpotIoEventsAndNodes:
    @parameterized.expand(
        [
            ("full_refresh", False, None, "2026-08-10"),
            ("first_incremental_sync", True, None, "2026-08-10"),
            ("incremental_from_string_watermark", True, "2026-11-01T17:10:04.000+0000", "2026-11-01"),
            ("incremental_from_datetime_watermark", True, datetime(2026, 10, 30, 23, 59, tzinfo=UTC), "2026-10-30"),
        ]
    )
    def test_events_from_date(self, _name, incremental, watermark, expected_from_date) -> None:
        with time_machine.travel(datetime(2026, 11, 8, 12, 0, tzinfo=UTC), tick=False):
            result = _run(
                "elastigroup_events",
                [_items({"id": "g1", "name": "n1"}), _items()],
                account_id="act-1",
                should_use_incremental_field=incremental,
                db_incremental_field_last_value=watermark,
                incremental_field="createdAt" if incremental else None,
            )

        child = result.requests[1]
        assert child.path == "/aws/ec2/group/g1/events"
        assert child.param("fromDate") == expected_from_date
        assert child.param("accountId") == "act-1"

    def test_events_get_a_stable_content_key(self) -> None:
        event = {"groupId": "g1", "eventType": "Update", "createdAt": "2026-11-01T17:10:04.000+0000"}
        script = [
            _items({"id": "g1", "name": "n1"}),
            _items(
                {**event, "subEvents": {"type": "scaleUp", "newInstances": ["i-1"]}},
                {**event, "subEvents": {"newInstances": ["i-1"], "type": "scaleUp"}},
                {**event, "subEvents": {"type": "scaleDown"}},
            ),
        ]

        rows = _run("elastigroup_events", script).rows

        assert [row["elastigroup_name"] for row in rows] == ["n1", "n1", "n1"]
        # Key order inside subEvents must not change the key, but different content must.
        assert rows[0]["event_key"] == rows[1]["event_key"]
        assert rows[0]["event_key"] != rows[2]["event_key"]
        assert len(rows[0]["event_key"]) == 64

    def test_nodes_carry_their_cluster_id(self) -> None:
        script = [
            _items({"id": "o-1"}, {"id": "o-2"}),
            _items({"instanceId": "i-1"}),
            _items({"instanceId": "i-2"}),
        ]

        result = _run("ocean_cluster_nodes", script, account_id="act-1")

        assert result.paths == [
            "/ocean/aws/k8s/cluster",
            "/ocean/aws/k8s/cluster/o-1/nodes",
            "/ocean/aws/k8s/cluster/o-2/nodes",
        ]
        assert result.rows == [
            {"instanceId": "i-1", "ocean_cluster_id": "o-1"},
            {"instanceId": "i-2", "ocean_cluster_id": "o-2"},
        ]
        assert all(request.param("accountId") == "act-1" for request in result.requests)
