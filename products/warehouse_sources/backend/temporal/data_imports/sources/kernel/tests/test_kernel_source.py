import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KernelSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kernel.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.kernel.source import KernelSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.kernel.source"


class TestKernelSource:
    def setup_method(self) -> None:
        self.source = KernelSource()
        self.team_id = 123
        self.config = KernelSourceConfig(api_key="sk_test")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.KERNEL

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Kernel"
        assert config.label == "Kernel"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/kernel"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_generated_config_parses_api_key(self) -> None:
        # Guards the hand-checked generated_configs.py edit: the form field must map to `api_key`.
        config = KernelSourceConfig.from_dict({"api_key": "sk_123"})
        assert config.api_key == "sk_123"

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        documented = {t["name"] for t in self.source.get_documented_tables()}
        assert documented == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.onkernel.com/apps?limit=1",
            "403 Client Error: Forbidden for url: https://api.onkernel.com/invocations?limit=100&offset=0",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.onkernel.com/apps",
        ],
    )
    def test_non_retryable_errors_ignore_unrelated(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["invocations"])
        assert [s.name for s in schemas] == ["invocations"]

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "probe_result, schema_name, expected_valid",
        [
            # Valid token.
            ((True, 200), None, True),
            # Bad token is always rejected.
            ((False, 401), None, False),
            # A 403 at source-create means valid token / missing scope - do not block creation.
            ((False, 403), None, True),
            # A 403 while probing a specific schema is a real scope failure for that table.
            ((False, 403), "invocations", False),
            ((False, None), None, False),
        ],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_kernel_credentials")
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        probe_result: tuple[bool, int | None],
        schema_name: str | None,
        expected_valid: bool,
    ) -> None:
        mock_validate.return_value = probe_result

        is_valid, _error = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        mock_validate.assert_called_once_with("sk_test")

    @mock.patch(f"{_SOURCE_MODULE}.kernel_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_kernel_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "invocations"

        self.source.source_for_pipeline(self.config, inputs)

        kwargs = mock_kernel_source.call_args.kwargs
        assert kwargs["api_key"] == "sk_test"
        assert kwargs["endpoint"] == "invocations"
