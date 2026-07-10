from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.netlify import NetlifyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.source import NetlifySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestNetlifySourceConfig:
    def test_source_type(self) -> None:
        assert NetlifySource().source_type == ExternalDataSourceType.NETLIFY

    def test_source_config_shape(self) -> None:
        config = NetlifySource().get_source_config
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/netlify"

    def test_single_password_token_field(self) -> None:
        fields = NetlifySource().get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_token"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True


class TestNetlifyGetSchemas:
    def test_all_endpoints_full_refresh(self) -> None:
        schemas = NetlifySource().get_schemas(mock.Mock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Netlify has no server-side timestamp filter, so no table supports incremental/append.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_names_filter(self) -> None:
        schemas = NetlifySource().get_schemas(mock.Mock(), team_id=1, names=["sites", "deploys"])
        assert {s.name for s in schemas} == {"sites", "deploys"}


class TestNetlifyValidateCredentials:
    def test_success(self) -> None:
        with mock.patch.object(source_module, "validate_netlify_credentials", return_value=True):
            assert NetlifySource().validate_credentials(mock.Mock(), team_id=1) == (True, None)

    def test_failure(self) -> None:
        with mock.patch.object(source_module, "validate_netlify_credentials", return_value=False):
            ok, error = NetlifySource().validate_credentials(mock.Mock(), team_id=1)
        assert ok is False
        assert error is not None


class TestNetlifyNonRetryableErrors:
    def test_auth_errors_present(self) -> None:
        errors = NetlifySource().get_non_retryable_errors()
        assert any(key.startswith("401 Client Error") for key in errors)
        assert any(key.startswith("403 Client Error") for key in errors)


class TestNetlifyCanonicalDescriptions:
    def test_covers_every_endpoint(self) -> None:
        descriptions = NetlifySource().get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)


class TestNetlifyResumableWiring:
    def test_resumable_manager_bound_to_resume_config(self) -> None:
        inputs = mock.Mock()
        inputs.logger = mock.Mock()
        manager = NetlifySource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is NetlifyResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        config = mock.Mock(api_token="nfp_secret")
        inputs = mock.Mock(schema_name="deploys")
        inputs.logger = mock.Mock()
        manager = mock.Mock()

        with mock.patch.object(source_module, "netlify_source") as netlify_source_mock:
            NetlifySource().source_for_pipeline(config, manager, inputs)

        netlify_source_mock.assert_called_once_with(
            api_token="nfp_secret",
            endpoint="deploys",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )
