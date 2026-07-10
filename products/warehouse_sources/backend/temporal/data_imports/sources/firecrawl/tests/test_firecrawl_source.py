from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.firecrawl import FirecrawlResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.source import FirecrawlSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FirecrawlSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> FirecrawlSourceConfig:
    return FirecrawlSourceConfig(api_key="fc-test")


class TestFirecrawlSourceConfig:
    def test_source_type(self) -> None:
        assert FirecrawlSource().source_type == ExternalDataSourceType.FIRECRAWL

    def test_api_key_field_is_a_required_secret(self) -> None:
        # A non-secret / non-password api_key field would render in plaintext and leak the credential.
        fields = {f.name: f for f in FirecrawlSource().get_source_config.fields}
        api_key = fields["api_key"]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.required is True
        assert api_key.secret is True
        assert api_key.type == SourceFieldInputConfigType.PASSWORD

    def test_released_as_alpha(self) -> None:
        assert FirecrawlSource().get_source_config.releaseStatus == ReleaseStatus.ALPHA


class TestFirecrawlGetSchemas:
    def test_every_endpoint_is_full_refresh_only(self) -> None:
        # Firecrawl has no server-side timestamp filter, so advertising incremental/append would be a
        # false promise: every sync would still page the whole endpoint.
        schemas = FirecrawlSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False, schema.name
            assert schema.supports_append is False, schema.name
            assert schema.incremental_fields == []

    def test_monitor_checks_is_off_by_default(self) -> None:
        # It fans out one request per monitor, so it must not auto-enable on connect.
        schemas = {s.name: s for s in FirecrawlSource().get_schemas(_config(), team_id=1)}
        assert schemas["monitor_checks"].should_sync_default is False
        assert schemas["team_activity"].should_sync_default is True

    def test_names_filter_is_applied(self) -> None:
        schemas = FirecrawlSource().get_schemas(_config(), team_id=1, names=["team_activity"])
        assert [s.name for s in schemas] == ["team_activity"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        # lists_tables_without_credentials must stay True (static catalog) or the docs table vanishes.
        source = FirecrawlSource()
        assert source.lists_tables_without_credentials is True
        tables = source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)


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

    def test_source_for_pipeline_plumbs_api_key_and_endpoint(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "team_activity"
        manager = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.source.firecrawl_source"
        ) as mock_source:
            FirecrawlSource().source_for_pipeline(_config(), manager, inputs)
        _, kwargs = mock_source.call_args
        assert kwargs["api_key"] == "fc-test"
        assert kwargs["endpoint"] == "team_activity"
        assert kwargs["resumable_source_manager"] is manager
