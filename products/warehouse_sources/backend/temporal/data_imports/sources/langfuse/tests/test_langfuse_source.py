import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.source import LangfuseSource


class TestLangfuseSource:
    def setup_method(self):
        self.source = LangfuseSource()
        self.team_id = 123
        self.config = mock.MagicMock()
        self.config.host = "https://cloud.langfuse.com"
        self.config.public_key = "pk-lf-key"
        self.config.secret_key = "sk-lf-key"

    def test_v1_is_deprecated_advisory_and_default_is_v2(self):
        # New sources start on v2; v1 stays supported so already-pinned rows keep resolving to the
        # unchanged wire. Langfuse announced no sunset date, so the deprecation is advisory
        # (sunset_at is None) — the generic in-product warning fires but no repin migration ships.
        assert self.source.default_version == "v2"
        assert set(self.source.supported_versions) == {"v1", "v2"}

        deprecation = self.source.get_version_deprecation("v1")
        assert deprecation is not None
        assert deprecation.sunset_at is None
        assert self.source.get_version_deprecation("v2") is None

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

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

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
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is incremental

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["traces"])
        assert len(schemas) == 1
        assert schemas[0].name == "traces"
