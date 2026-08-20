import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.canvas_lms import CanvasLmsResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.source import CanvasLmsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.canvaslms import (
    CanvasLmsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCanvasLmsSource:
    def setup_method(self):
        self.source = CanvasLmsSource()
        self.team_id = 123
        self.config = CanvasLmsSourceConfig(canvas_domain="yourschool.instructure.com", account_id="1", api_key="tok")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CANVASLMS

    def test_connection_host_fields(self):
        assert self.source.connection_host_fields == ["canvas_domain", "account_id"]

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "CanvasLms"
        assert config.label == "Instructure Canvas LMS"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/canvas_lms.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["canvas_domain", "account_id", "api_key"]

        domain_field, account_field, token_field = config.fields
        assert isinstance(domain_field, SourceFieldInputConfig)
        assert domain_field.type == SourceFieldInputConfigType.TEXT
        assert domain_field.secret is False

        assert isinstance(account_field, SourceFieldInputConfig)
        assert account_field.type == SourceFieldInputConfigType.TEXT
        assert account_field.secret is False

        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("courses", False),
            ("users", False),
            ("enrollments", False),
            ("assignments", False),
            ("submissions", True),
        ]
    )
    def test_schema_incremental_support(self, endpoint, incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental

    def test_submissions_is_merge_only(self):
        # Submissions mutate in place (grades change), so append-only would duplicate rows.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["submissions"].supports_incremental is True
        assert schemas["submissions"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["courses"])
        assert len(schemas) == 1
        assert schemas[0].name == "courses"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected",
        [
            ((True, None), (True, None)),
            ((False, "Invalid Canvas access token"), (False, "Invalid Canvas access token")),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.source.validate_canvas_lms_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="courses")

        assert result == expected
        mock_validate.assert_called_once_with(
            self.config.canvas_domain, self.config.account_id, self.config.api_key, "courses", self.team_id
        )

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CanvasLmsResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.source.canvas_lms_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_canvas_lms_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "submissions"
        inputs.team_id = 42
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"
        inputs.incremental_field = "submitted_at"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_canvas_lms_source.assert_called_once()
        kwargs = mock_canvas_lms_source.call_args.kwargs
        assert kwargs["domain"] == "yourschool.instructure.com"
        assert kwargs["account_id"] == "1"
        assert kwargs["api_key"] == "tok"
        assert kwargs["endpoint"] == "submissions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
        assert kwargs["job_id"] == "job-1"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "submitted_at"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.source.canvas_lms_source")
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_canvas_lms_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "courses"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_canvas_lms_source.call_args.kwargs["db_incremental_field_last_value"] is None
