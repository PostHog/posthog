import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zenduty import (
    ZendutySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zenduty.source import ZendutySource


class TestZendutyValidateCredentials:
    @parameterized.expand(
        [
            ("connection_failure_rejected", None, False),
        ]
    )
    def test_status_mapping(self, _name: str, probe_status: int | None, expected_ok: bool) -> None:
        def answer(_request: object) -> ScriptedResponse:
            if probe_status is None:
                raise requests.ConnectionError("boom")
            return ScriptedResponse(status=probe_status)

        with scripted_network(answer) as network:
            ok, error = ZendutySource().validate_credentials(ZendutySourceConfig(api_key="tok"), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok
        assert network.requests_log
        assert all(request.path == "/api/account/teams/" for request in network.requests_log)
        assert all(request.param("page_size") == "1" for request in network.requests_log)


class TestZendutyResumableAndPipeline:
    @parameterized.expand(
        [
            # Top-level endpoints key on the object's own id...
            ("incidents", ["unique_id"]),
            ("teams", ["unique_id"]),
            # ...fan-out children key on parent team + child id, unique table-wide.
            ("services", ["_zenduty_team_id", "unique_id"]),
            ("schedules", ["_zenduty_team_id", "unique_id"]),
        ]
    )
    def test_source_for_pipeline_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        result = SourceDriver(ZendutySource(), ZendutySourceConfig(api_key="tok")).run(
            endpoint, [ScriptedResponse(json={"results": [], "next": None})]
        )
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        # No partitioning until the stable creation-date column is confirmed per endpoint.
        assert response.partition_keys is None
        assert response.partition_mode is None
