import pytest

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sigmacomputing import (
    SigmaComputingSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sigma_computing.settings import REGION_HOSTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sigma_computing.source import (
    REGION_OPTIONS,
    SigmaComputingSource,
)


class TestSigmaComputingSource:
    def setup_method(self) -> None:
        self.source = SigmaComputingSource()
        self.team_id = 123
        self.config = SigmaComputingSourceConfig(client_id="client-id", client_secret="client-secret", region="gcp_us")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "SigmaComputing"
        assert config.label == "Sigma Computing"
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source ships visible: unreleasedSource hides the connector from every user.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/sigma_computing.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/sigma-computing"

    def test_connection_host_fields(self) -> None:
        # `region` picks the host the client secret is sent to, so retargeting it must
        # re-require the secret.
        assert self.source.connection_host_fields == ["region"]

    def test_region_options_constant_matches_settings(self) -> None:
        assert {option.value for option in REGION_OPTIONS} == set(REGION_HOSTS)

    def test_get_schemas_are_full_refresh_only(self) -> None:
        # Sigma's list endpoints expose no server-side updated-since filter.
        schemas = self.source.get_schemas(self.config, self.team_id)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.sigmacomputing.com/v2/workbooks",
            "403 Client Error: Forbidden for url: https://api.sigmacomputing.com/v2/workbooks",
            "Sigma rejected the API client credentials (HTTP 401)",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient_failures(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            key in "500 Server Error for url: https://api.sigmacomputing.com/v2/workbooks" for key in non_retryable
        )
