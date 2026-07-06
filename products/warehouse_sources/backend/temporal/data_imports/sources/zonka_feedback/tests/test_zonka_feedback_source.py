import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ZonkaFeedbackSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.source import ZonkaFeedbackSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.zonka_feedback import (
    ZonkaFeedbackResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestZonkaFeedbackSource:
    def setup_method(self) -> None:
        self.source = ZonkaFeedbackSource()
        self.team_id = 123
        self.config = ZonkaFeedbackSourceConfig(auth_token="zonka-token", data_center="us1")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ZONKAFEEDBACK

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Zonka Feedback"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/zonka-feedback"

        input_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        select_names = [f.name for f in config.fields if isinstance(f, SourceFieldSelectConfig)]
        assert input_names == ["auth_token"]
        assert select_names == ["data_center"]

    def test_auth_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "auth_token")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_data_center_options_cover_known_regions(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig) and f.name == "data_center")
        assert {o.value for o in field.options} == {"us1", "e", "in"}
        assert field.defaultValue == "us1"

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["surveys"])
        assert len(schemas) == 1
        assert schemas[0].name == "surveys"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://us1.apis.zonkafeedback.com/responses?page=1&page_size=100",
            "403 Client Error: Forbidden for url: https://e.apis.zonkafeedback.com/surveys?page=2&page_size=100",
            "401 Client Error: Unauthorized for url: https://in.apis.zonkafeedback.com/contacts?page=1&page_size=100",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "500 Server Error: Internal Server Error for url: https://us1.apis.zonkafeedback.com/responses",
            "HTTPSConnectionPool(host='us1.apis.zonkafeedback.com', port=443): Read timed out.",
            "429 Client Error: Too Many Requests for url: https://e.apis.zonkafeedback.com/surveys",
        ],
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Zonka Feedback auth token"),
            (403, False, "Invalid Zonka Feedback auth token"),
            (500, False, "Zonka Feedback returned HTTP 500"),
            (0, False, "Could not connect to Zonka Feedback: boom"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.source.check_access")
    def test_validate_credentials(
        self,
        mock_check: mock.MagicMock,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        message = (
            "Zonka Feedback returned HTTP 500"
            if status == 500
            else ("Could not connect to Zonka Feedback: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.source.check_access")
    def test_validate_credentials_probes_the_auth_token(self, mock_check: mock.MagicMock) -> None:
        # The auth token is account-wide, so validation probes the token, not a per-schema scope.
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="surveys")
        mock_check.assert_called_once_with("zonka-token", "us1")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ZonkaFeedbackResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.source.zonka_feedback_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "responses"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["auth_token"] == "zonka-token"
        assert kwargs["data_center"] == "us1"
        assert kwargs["endpoint"] == "responses"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Zonka Feedback schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
