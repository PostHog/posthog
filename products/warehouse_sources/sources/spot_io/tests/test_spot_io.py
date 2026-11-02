import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.spotio import SpotIoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.source import SpotIoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.spot_io import (
    SpotIoResumeConfig,
    _account_params,
    get_resource,
    validate_credentials,
)


def _items(*items: dict[str, str]) -> ScriptedResponse:
    return ScriptedResponse(json={"response": {"items": list(items)}})


def _run(
    endpoint: str,
    script: list[ScriptedResponse],
    resume_state: SpotIoResumeConfig | None = None,
    account_id: str | None = None,
) -> DriveResult:
    config = SpotIoSourceConfig(api_token="token", account_id=account_id)
    return SourceDriver(SpotIoSource(), config).run(endpoint, script, resume_state=resume_state)


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
