from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.source import CastAiSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.castai import CastAiSourceConfig


class TestCastAiSource:
    def setup_method(self) -> None:
        self.source = CastAiSource()
        self.team_id = 123
        self.config = CastAiSourceConfig(api_key="castai-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "CastAi"
        assert config.label == "CAST AI"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source ships visible: unreleasedSource hides the connector from every user.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/cast_ai.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/cast-ai"

    def test_get_schemas_incremental_semantics(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        # No server-side timestamp filter is documented for listing clusters, so it stays
        # full refresh.
        assert schemas["clusters"].supports_incremental is False
        assert schemas["clusters"].incremental_fields == []

        for name, field_name in (("cluster_cost_reports", "timestamp"), ("cluster_savings_history", "createdAt")):
            assert schemas[name].supports_incremental is True
            assert [f["field"] for f in schemas[name].incremental_fields] == [field_name]

    @parameterized.expand(
        [
            "401 Client Error: Unauthorized for url: https://api.cast.ai/v1/kubernetes/external-clusters",
            "403 Client Error: Forbidden for url: https://api.cast.ai/v1/kubernetes/external-clusters",
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient_failures(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            key in "500 Server Error for url: https://api.cast.ai/v1/kubernetes/external-clusters"
            for key in non_retryable
        )
