import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sageintacct import (
    SageIntacctSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.sage_intacct import (
    SageIntacctResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELD_QUERY_PATHS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.source import SageIntacctSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.source"


class TestSageIntacctSource:
    def setup_method(self) -> None:
        self.source = SageIntacctSource()
        self.team_id = 123
        self.config = SageIntacctSourceConfig(client_id="cid", client_secret="sec", refresh_token="ref")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SAGEINTACCT

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.label == "Sage Intacct"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/sage_intacct.png"
        assert [field.name for field in config.fields] == ["client_id", "client_secret", "refresh_token"]

    @pytest.mark.parametrize(
        "field_name, is_secret, is_required",
        [
            ("client_id", False, True),
            ("client_secret", True, True),
            # Blank refresh token means the client credentials grant.
            ("refresh_token", True, False),
        ],
    )
    def test_credential_fields(self, field_name: str, is_secret: bool, is_required: bool) -> None:
        field = next(
            f
            for f in self.source.get_source_config.fields
            if isinstance(f, SourceFieldInputConfig) and f.name == field_name
        )

        assert field.secret is is_secret
        assert field.required is is_required
        assert field.type == (SourceFieldInputConfigType.PASSWORD if is_secret else SourceFieldInputConfigType.TEXT)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.intacct.com/ia/api/v1/oauth2/token",
            "400 Client Error: Bad Request for url: https://api.intacct.com/ia/api/v1/oauth2/token",
            "403 Client Error: Forbidden for url: https://api.intacct.com/ia/api/v1/services/core/query",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.intacct.com/ia/api/v1/services/core/query",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_covers_every_endpoint_incrementally(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Every standard object carries an audit block the query service can filter on.
        assert all(schema.supports_incremental for schema in schemas)

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_advertised_incremental_fields_are_queryable(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        assert schema.incremental_fields == INCREMENTAL_FIELDS[endpoint]
        assert all(field["field"] in INCREMENTAL_FIELD_QUERY_PATHS for field in schema.incremental_fields)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["ar_invoices"])

        assert [schema.name for schema in schemas] == ["ar_invoices"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_canonical_descriptions_cover_the_advertised_tables(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert descriptions is CANONICAL_DESCRIPTIONS
        assert set(descriptions) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Sage Intacct credentials"),
        ],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_sage_intacct_credentials")
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        probe_result: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = probe_result

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("cid", "sec", "ref")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SageIntacctResumeConfig

    @mock.patch(f"{_SOURCE_MODULE}.sage_intacct_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "ar_invoices"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "audit_modifiedDateTime"
        inputs.db_incremental_field_last_value = "2024-05-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["client_id"] == "cid"
        assert kwargs["client_secret"] == "sec"
        assert kwargs["refresh_token"] == "ref"
        assert kwargs["endpoint"] == "ar_invoices"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["incremental_field"] == "audit_modifiedDateTime"
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01T00:00:00Z"

    @mock.patch(f"{_SOURCE_MODULE}.sage_intacct_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "vendors"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-05-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
