from typing import Any, cast

import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.fillout.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fillout.source import FilloutSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FilloutSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestFilloutSource:
    def setup_method(self) -> None:
        self.source = FilloutSource()
        self.team_id = 123
        self.config = FilloutSourceConfig(api_key="fillout-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.FILLOUT

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Fillout"
        assert config.label == "Fillout"
        assert config.category == DataWarehouseSourceCategory.PRODUCTIVITY
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/fillout.png"

    def test_source_config_fields(self) -> None:
        config = self.source.get_source_config
        input_fields = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        select_fields = [f.name for f in config.fields if isinstance(f, SourceFieldSelectConfig)]
        assert input_fields == ["api_key"]
        assert select_fields == ["api_base_url"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_semantics(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        # `forms` only exposes formId/name — no server-side timestamp filter, so full refresh.
        assert schemas["forms"].supports_incremental is False
        assert schemas["forms"].incremental_fields == []

        # `submissions` supports incremental via the server-side `afterDate` filter on submissionTime.
        assert schemas["submissions"].supports_incremental is True
        assert schemas["submissions"].supports_append is True
        assert [f["field"] for f in schemas["submissions"].incremental_fields] == ["submissionTime"]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["submissions"])
        assert len(schemas) == 1
        assert schemas[0].name == "submissions"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.fillout.com/v1/api/forms",
            "403 Client Error: Forbidden for url: https://api.fillout.com/v1/api/forms",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        ["500 Server Error for url: https://api.fillout.com/v1/api/forms"],
    )
    def test_non_retryable_errors_ignore_unrelated(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    def test_validate_credentials_rejects_unknown_api_base_url(self) -> None:
        config = FilloutSourceConfig(api_key="fillout-key", api_base_url=cast(Any, "https://api.fillout.com"))
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message is not None and "API base URL must be one of" in message

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.fillout.source.validate_fillout_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        result = self.source.validate_credentials(self.config, self.team_id, schema_name="submissions")

        assert result == (True, None)
        kwargs = mock_validate.call_args.kwargs
        assert kwargs["api_key"] == "fillout-key"
        assert kwargs["api_base_url"] == "https://api.fillout.com/v1/api"
        assert kwargs["schema_name"] == "submissions"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.fillout.source.fillout_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_fillout_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "submissions"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "submissionTime"

        self.source.source_for_pipeline(self.config, inputs)

        mock_fillout_source.assert_called_once()
        kwargs = mock_fillout_source.call_args.kwargs
        assert kwargs["api_key"] == "fillout-key"
        assert kwargs["endpoint"] == "submissions"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["incremental_field"] == "submissionTime"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.fillout.source.fillout_source")
    def test_source_for_pipeline_omits_watermark_when_not_incremental(
        self, mock_fillout_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "submissions"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, inputs)

        kwargs = mock_fillout_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
