from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.source import LangfuseSource


class TestLangfuseSource:
    def setup_method(self):
        self.source = LangfuseSource()
        self.team_id = 123
        self.config = mock.MagicMock()
        self.config.host = "https://cloud.langfuse.com"
        self.config.public_key = "pk-lf-key"
        self.config.secret_key = "sk-lf-key"

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

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["traces"])
        assert len(schemas) == 1
        assert schemas[0].name == "traces"
