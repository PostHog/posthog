from datetime import date

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.langfuse import (
    LangfuseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.settings import (
    ENDPOINTS,
    endpoints_for_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.source import LangfuseSource


class TestLangfuseSource:
    def setup_method(self):
        self.source = LangfuseSource()
        self.team_id = 123
        self.config = mock.MagicMock()
        self.config.host = "https://cloud.langfuse.com"
        self.config.public_key = "pk-lf-key"
        self.config.secret_key = "sk-lf-key"

    def test_legacy_versions_carry_the_vendor_sunset_and_default_is_v3(self):
        assert self.source.default_version == "v3"
        assert self.source.supported_versions == ("v1", "v2", "v3")

        for legacy in ("v1", "v2"):
            deprecation = self.source.get_version_deprecation(legacy)
            assert deprecation is not None
            assert deprecation.sunset_at == date(2026, 11, 16)
        assert self.source.get_version_deprecation("v3") is None

    def test_endpoints_for_version_rejects_an_unknown_pin(self):
        with pytest.raises(ValueError, match="Unsupported Langfuse API version"):
            endpoints_for_version("v4")

    def test_exhausted_connection_pool_error_is_classified_retryable(self):
        # Matches the message urllib3 raises once `get_rows`'s tenacity retry (which covers read
        # timeouts and connection failures, not just 429/422/5xx) exhausts its budget — keeps this
        # transient, self-recovering failure out of error tracking instead of reaching
        # `logger.aexception`.
        observed_error = (
            "HTTPSConnectionPool(host='us.cloud.langfuse.com', port=443): Max retries exceeded with "
            "url: /api/public/traces?limit=50&orderBy=timestamp.asc&page=5339 (Caused by "
            "ReadTimeoutError(\"HTTPSConnectionPool(host='us.cloud.langfuse.com', port=443): "
            'Read timed out. (read timeout=60)"))'
        )
        assert any(pattern in observed_error for pattern in self.source.get_retryable_errors())

    @pytest.mark.parametrize(
        "api_version, expected",
        [
            ("v1", set(ENDPOINTS)),
            ("v2", set(ENDPOINTS)),
            ("v3", set(ENDPOINTS) - {"traces", "sessions"}),
            (None, set(ENDPOINTS) - {"traces", "sessions"}),
        ],
    )
    def test_get_schemas_discovers_the_pinned_version_catalog(self, api_version, expected):
        schemas = self.source.get_schemas(self.config, self.team_id, api_version=api_version)
        assert {s.name for s in schemas} == expected

    @pytest.mark.parametrize(
        "api_version, endpoint",
        [("v1", "traces"), ("v2", "sessions"), ("v3", "observations")],
    )
    def test_source_for_pipeline_reads_tables_served_by_the_pin(self, api_version, endpoint):
        driver = SourceDriver(
            self.source,
            LangfuseSourceConfig(host="https://cloud.langfuse.com", public_key="pk-lf-key", secret_key="sk-lf-key"),
        )
        result = driver.run(
            endpoint, [ScriptedResponse(json={"data": [], "meta": {"totalPages": 1}})], api_version=api_version
        )
        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint

    @pytest.mark.parametrize("endpoint", ["traces", "sessions"])
    def test_v3_refuses_retired_tables_with_a_non_retryable_error(self, endpoint):
        driver = SourceDriver(
            self.source,
            LangfuseSourceConfig(host="https://cloud.langfuse.com", public_key="pk-lf-key", secret_key="sk-lf-key"),
        )
        result = driver.run(endpoint, [], api_version="v3")
        assert isinstance(result.raised, ValueError)
        assert result.requests == []
        assert any(pattern in str(result.raised) for pattern in self.source.get_non_retryable_errors())
