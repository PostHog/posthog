from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig, SourceFieldInputConfigType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.firecrawl import FirecrawlResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.source import FirecrawlSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.firecrawl import (
    FirecrawlSourceConfig,
)


def _config() -> FirecrawlSourceConfig:
    return FirecrawlSourceConfig(api_key="fc-test")


class TestFirecrawlSourceConfig:
    def test_api_key_field_is_a_required_secret(self) -> None:
        # A non-secret / non-password api_key field would render in plaintext and leak the credential.
        fields = {f.name: f for f in FirecrawlSource().get_source_config.fields}
        api_key = fields["api_key"]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.required is True
        assert api_key.secret is True
        assert api_key.type == SourceFieldInputConfigType.PASSWORD


class TestFirecrawlGetSchemas:
    def test_names_filter_is_applied(self) -> None:
        schemas = FirecrawlSource().get_schemas(_config(), team_id=1, names=["team_activity"])
        assert [s.name for s in schemas] == ["team_activity"]


class TestFirecrawlValidateCredentials:
    @parameterized.expand([("valid", True), ("invalid", False)])
    def test_maps_token_probe_to_result(self, _name: str, probe_result: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.source.validate_firecrawl_credentials",
            return_value=probe_result,
        ):
            ok, error = FirecrawlSource().validate_credentials(_config(), team_id=1)
        assert ok is probe_result
        assert (error is None) is probe_result


class TestFirecrawlNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.firecrawl.dev/v2/team/activity"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.firecrawl.dev/v2/monitor"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        errors = FirecrawlSource().get_non_retryable_errors()
        assert any(key in observed for key in errors)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.firecrawl.dev/v2/monitor"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.firecrawl.dev/v2/team/activity"),
            ("read_timeout", "HTTPSConnectionPool(host='api.firecrawl.dev', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, observed: str) -> None:
        errors = FirecrawlSource().get_non_retryable_errors()
        assert not any(key in observed for key in errors)


class TestFirecrawlResumableWiring:
    def test_manager_is_bound_to_resume_config(self) -> None:
        # A wrong data class would deserialize saved Redis state into the wrong shape on resume.
        inputs = MagicMock()
        manager = FirecrawlSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FirecrawlResumeConfig
