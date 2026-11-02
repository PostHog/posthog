from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig, SourceFieldInputConfigType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mistralai import (
    MistralAISourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mistral_ai.source import MistralAISource


def _config() -> MistralAISourceConfig:
    return MistralAISourceConfig(api_key="sk-x")


class TestSourceConfig:
    def test_api_key_field_is_required_secret_password(self) -> None:
        # A non-secret key field would persist the API key in plaintext job inputs.
        fields = MistralAISource().get_source_config.fields
        assert len(fields) == 1
        api_key = fields[0]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.name == "api_key"
        assert api_key.required is True
        assert api_key.secret is True
        assert api_key.type == SourceFieldInputConfigType.PASSWORD


class TestGetSchemas:
    @parameterized.expand(
        [
            ("fine_tuning_jobs", True),
            ("batch_jobs", True),
            ("files", False),
            ("models", False),
            ("agents", False),
            ("conversations", False),
            ("libraries", False),
        ]
    )
    def test_incremental_only_where_server_filter_exists(self, endpoint: str, supports_incremental: bool) -> None:
        # Only fine-tuning and batch jobs expose a server-side created_after filter; the rest must ship
        # full refresh, never advertise incremental they can't honor.
        schemas = {s.name: s for s in MistralAISource().get_schemas(_config(), team_id=1)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_incremental
        if supports_incremental:
            assert [f["field"] for f in schema.incremental_fields] == ["created_at"]
        else:
            assert schema.incremental_fields == []

    @parameterized.expand([("agents", False), ("conversations", False), ("libraries", False), ("files", True)])
    def test_beta_endpoints_off_by_default(self, endpoint: str, should_sync_default: bool) -> None:
        schemas = {s.name: s for s in MistralAISource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].should_sync_default is should_sync_default


class TestValidateCredentials:
    @parameterized.expand([("valid", 200, (True, None))])
    def test_maps_probe_result(self, _name: str, status: int, expected: tuple[bool, str | None]) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            result = MistralAISource().validate_credentials(_config(), team_id=1)
        assert result == expected
        assert [request.path for request in network.requests_log] == ["/v1/models"]
        assert network.requests_log[0].headers["authorization"] == "Bearer sk-x"


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "page_zero",
                "410 Client Error: Gone for url: https://api.mistral.ai/v1/fine_tuning/jobs?page=0&page_size=100",
            ),
            (
                "later_page",
                "410 Client Error: Gone for url: https://api.mistral.ai/v1/fine_tuning/jobs?page=3&page_size=100",
            ),
        ]
    )
    def test_fine_tuning_gone_is_non_retryable(self, _name: str, observed: str) -> None:
        # Mistral's 410 means fine-tuning is unavailable for the workspace, not a page-specific fluke,
        # so the match must hold regardless of which page the pagination loop was on.
        assert any(key in observed for key in MistralAISource().get_non_retryable_errors())


class TestPipelinePlumbing:
    def test_source_for_pipeline_drops_watermark_when_not_incremental(self) -> None:
        # Passing a stale watermark on a full-refresh run would build a bogus created_after filter.
        result = SourceDriver(MistralAISource(), _config()).run(
            "batch_jobs",
            [ScriptedResponse(json={"data": []})],
            should_use_incremental_field=False,
            db_incremental_field_last_value=1_772_000_000,
        )
        assert result.raised is None
        assert result.requests[0].param("created_after") is None
