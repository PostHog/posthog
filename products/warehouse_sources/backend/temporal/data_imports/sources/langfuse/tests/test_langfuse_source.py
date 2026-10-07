from datetime import date

import pytest
from unittest import mock

from products.warehouse_sources.backend.facade.source_config import (
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Langfuse"
        assert config.label == "Langfuse"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/langfuse.svg"

        field_names = [f.name for f in config.fields]
        assert field_names == ["host", "public_key", "secret_key"]

        host_field, public_key_field, secret_key_field = config.fields
        assert isinstance(host_field, SourceFieldInputConfig)
        assert host_field.type == SourceFieldInputConfigType.TEXT
        assert host_field.required is False
        assert host_field.secret is False

        assert isinstance(public_key_field, SourceFieldInputConfig)
        assert public_key_field.required is True
        assert public_key_field.secret is False

        # The secret key must stay a secret password field: the serializer derives which config
        # keys are sensitive from these flags.
        assert isinstance(secret_key_field, SourceFieldInputConfig)
        assert secret_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_key_field.secret is True
        assert secret_key_field.required is True

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
        inputs = mock.MagicMock(api_version=api_version, schema_name=endpoint, should_use_incremental_field=False)
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.source.langfuse_source"
        ) as langfuse_source:
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
        assert langfuse_source.call_args.kwargs["endpoint"] == endpoint

    @pytest.mark.parametrize("endpoint", ["traces", "sessions"])
    def test_v3_refuses_retired_tables_with_a_non_retryable_error(self, endpoint):
        inputs = mock.MagicMock(api_version="v3", schema_name=endpoint)
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.source.langfuse_source"
        ) as langfuse_source:
            with pytest.raises(ValueError) as exc_info:
                self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
        langfuse_source.assert_not_called()
        assert any(pattern in str(exc_info.value) for pattern in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "endpoint, incremental",
        [
            ("traces", True),
            ("observations", True),
            ("scores", True),
            ("sessions", True),
            ("prompts", True),
            ("datasets", False),
            ("dataset_items", False),
            ("models", False),
        ],
    )
    def test_schema_incremental_support(self, endpoint, incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id, api_version="v2")}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is incremental

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["observations"])
        assert len(schemas) == 1
        assert schemas[0].name == "observations"
