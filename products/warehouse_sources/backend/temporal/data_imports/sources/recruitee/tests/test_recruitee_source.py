import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RecruiteeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.recruitee import RecruiteeResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.source import RecruiteeSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestRecruiteeSource:
    def setup_method(self) -> None:
        self.source = RecruiteeSource()
        self.team_id = 123
        self.config = RecruiteeSourceConfig(company_id="acme", api_token="rc-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.RECRUITEE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Recruitee"
        assert config.label == "Recruitee"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/recruitee"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["company_id", "api_token"]

    def test_company_id_field_is_non_secret_text(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "company_id")
        assert field.type == SourceFieldInputConfigType.TEXT
        assert field.secret is False
        assert field.required is True

    def test_api_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_connection_host_fields_pins_company_id(self) -> None:
        # The secret token is sent to a path derived from company_id, so retargeting the company ID
        # must re-require the token.
        assert self.source.connection_host_fields == ["company_id"]

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["offers"])
        assert len(schemas) == 1
        assert schemas[0].name == "offers"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.recruitee.com/c/acme/candidates?limit=100&offset=0",),
            ("403 Client Error: Forbidden for url: https://api.recruitee.com/c/acme/offers?limit=100&offset=0",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.recruitee.com/c/acme/candidates",),
            ("429 Client Error: Too Many Requests for url: https://api.recruitee.com/c/acme/offers",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Recruitee company ID or API token"),
            (403, False, "Invalid Recruitee company ID or API token"),
            (500, False, "Recruitee returned HTTP 500"),
            (0, False, "Could not connect to Recruitee: boom"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.recruitee.check_access")
    def test_validate_credentials(
        self,
        mock_check: mock.MagicMock,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        message = (
            "Recruitee returned HTTP 500"
            if status == 500
            else ("Could not connect to Recruitee: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is RecruiteeResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.source.recruitee_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "candidates"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["company_id"] == "acme"
        assert kwargs["api_token"] == "rc-token"
        assert kwargs["endpoint"] == "candidates"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Recruitee schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
