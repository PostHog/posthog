from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MixMaxSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.mixmax import MixmaxResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.source import MixMaxSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> MixMaxSourceConfig:
    return MixMaxSourceConfig(api_key="tok")


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert MixMaxSource().source_type == ExternalDataSourceType.MIXMAX

    def test_config_advertises_a_single_password_api_token_field(self) -> None:
        config = MixMaxSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.SALES
        assert len(config.fields) == 1
        field = config.fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True

    def test_source_is_alpha_and_still_hidden(self) -> None:
        # Ships as alpha and stays hidden (unreleasedSource) until verified against a live workspace.
        config = MixMaxSource().get_source_config
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True

    def test_docs_url_matches_published_doc_slug(self) -> None:
        assert MixMaxSource().get_source_config.docsUrl == "https://posthog.com/docs/cdp/sources/mixmax"


class TestGetSchemas:
    def test_all_schemas_are_full_refresh_only(self) -> None:
        # Mixmax exposes no server-side timestamp filter, so nothing may advertise incremental/append.
        schemas = MixMaxSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_names_filter_restricts_returned_schemas(self) -> None:
        schemas = MixMaxSource().get_schemas(_config(), team_id=1, names=["sequences", "live_feed"])
        assert {s.name for s in schemas} == {"sequences", "live_feed"}

    def test_documented_tables_render_for_public_docs(self) -> None:
        # `lists_tables_without_credentials` lets the posthog.com Supported tables section render
        # without connecting — the catalog must come back non-empty and carry curated descriptions.
        tables = MixMaxSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        sequences = next(t for t in tables if t["name"] == "sequences")
        assert sequences["sync_methods"] == ["Full refresh"]
        assert sequences["description"]


class TestValidateCredentials:
    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Mixmax API token"))])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected: tuple[bool, str | None]) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.source.validate_mixmax_credentials",
            return_value=probe_result,
        ):
            assert MixMaxSource().validate_credentials(_config(), team_id=1) == expected


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.mixmax.com/v1/sequences?limit=100"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.mixmax.com/v1/messages?limit=100"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        errors = MixMaxSource().get_non_retryable_errors()
        assert any(key in observed for key in errors)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.mixmax.com/v1/sequences"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.mixmax.com/v1/sequences"),
            ("read_timeout", "HTTPSConnectionPool(host='api.mixmax.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed: str) -> None:
        errors = MixMaxSource().get_non_retryable_errors()
        assert not any(key in observed for key in errors)


class TestResumableWiring:
    def test_resumable_manager_is_bound_to_mixmax_resume_config(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = MixMaxSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MixmaxResumeConfig

    def test_source_for_pipeline_plumbs_selected_endpoint(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "messages"
        inputs.logger = MagicMock()
        manager = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.source.mixmax_source"
        ) as mock_source:
            MixMaxSource().source_for_pipeline(_config(), manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["api_key"] == "tok"
        assert kwargs["endpoint"] == "messages"
        assert kwargs["resumable_source_manager"] is manager
