from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.source import BigMailerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bigmailer import (
    BigMailerSourceConfig,
)


class TestCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials_plumbing(self, _name: str, probe_result: bool, expected_ok: bool) -> None:
        status = 200 if probe_result else 403
        with scripted_network([ScriptedResponse(status=status)]) as network:
            ok, error = BigMailerSource().validate_credentials(BigMailerSourceConfig(api_key="key"), team_id=1)

        assert ok is expected_ok
        assert (error is None) is expected_ok
        assert network.requests_log[0].path == "/v1/brands"


class TestPipelineHandoff:
    @parameterized.expand([("contacts", ["brand_id", "id"]), ("brands", ["id"])])
    def test_source_for_pipeline_builds_response(self, endpoint: str, expected_keys: list[str]) -> None:
        result = SourceDriver(BigMailerSource(), BigMailerSourceConfig(api_key="key")).run(
            endpoint, [ScriptedResponse(json={"data": [], "has_more": False, "cursor": "ignored"})]
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_keys
