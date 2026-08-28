import pytest

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.logzio import LogzIOSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.source import LogzIOSource

SOURCE = "products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.source"


class TestLogzIOSource:
    def setup_method(self):
        self.source = LogzIOSource()
        self.team_id = 123
        self.config = LogzIOSourceConfig(api_token="token", region="us")

    def test_connection_host_fields_includes_region(self):
        # region picks the host the stored token is sent to, so editing it must re-require the secret.
        assert self.source.connection_host_fields == ["region"]

    def test_get_source_config(self):
        config = self.source.get_source_config
        assert config.name.value == "LogzIO"
        assert config.label == "Logz.io"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/logz-io"
        # A finished source must never keep the scaffold's unreleasedSource flag (it hides the source).
        assert config.unreleasedSource is None

    def test_lists_tables_without_credentials(self):
        # get_schemas iterates a static endpoint catalog with no I/O, so the public docs catalog renders.
        assert self.source.lists_tables_without_credentials is True
        documented = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(documented) == set(ENDPOINTS)
        assert "Incremental" in documented["search_logs"]["sync_methods"]
        assert documented["alerts"]["sync_methods"] == ["Full refresh"]

    @pytest.mark.parametrize(
        "endpoint, expected_incremental",
        [
            # Only search_logs has a genuine server-side time filter (the ES @timestamp range query).
            ("search_logs", True),
            ("alerts", False),
            ("triggered_alerts", False),
            ("notification_endpoints", False),
            ("drop_filters", False),
        ],
    )
    def test_incremental_support_per_endpoint(self, endpoint: str, expected_incremental: bool):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(ENDPOINTS)
        assert schemas[endpoint].supports_incremental is expected_incremental
        assert schemas[endpoint].incremental_fields == INCREMENTAL_FIELDS[endpoint]

    def test_get_schemas_filtered_by_names(self):
        assert [s.name for s in self.source.get_schemas(self.config, self.team_id, names=["alerts"])] == ["alerts"]
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.logz.io/v1/scroll",
            "403 Client Error: Forbidden for url: https://api-eu.logz.io/v2/alerts",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error: Internal Server Error for url: https://api.logz.io/v1/scroll",
            "429 Client Error: Too Many Requests for url: https://api.logz.io/v1/scroll",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_ignore_transient_and_unrelated(self, other_error: str):
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())
