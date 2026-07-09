from typing import cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SurveySparrowSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.source import (
    SurveySparrowSource,
    _base_url_for,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.surveysparrow import (
    SurveySparrowResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.source"


def _config(access_token: str = "token", data_center: str = "us") -> SurveySparrowSourceConfig:
    return SurveySparrowSourceConfig(access_token=access_token, data_center=data_center)  # type: ignore[arg-type]


class TestSurveySparrowSourceType:
    def test_source_type(self) -> None:
        assert SurveySparrowSource().source_type == ExternalDataSourceType.SURVEYSPARROW


class TestSurveySparrowSourceConfigFields:
    def test_exposes_access_token_and_data_center(self) -> None:
        cfg = SurveySparrowSource().get_source_config

        names = {f.name for f in cfg.fields}
        assert names == {"access_token", "data_center"}

        token_field = next(f for f in cfg.fields if f.name == "access_token")
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.required is True
        assert token_field.secret is True

        dc_field = next(f for f in cfg.fields if f.name == "data_center")
        assert isinstance(dc_field, SourceFieldSelectConfig)
        assert dc_field.defaultValue == "us"
        assert {opt.value for opt in dc_field.options} == {"us", "eu", "ap", "me", "uk", "ap-sy", "ca"}

    def test_release_status_is_alpha(self) -> None:
        assert SurveySparrowSource().get_source_config.releaseStatus == ReleaseStatus.ALPHA


class TestBaseUrlFor:
    @parameterized.expand(
        [
            ("us", "us", "https://api.surveysparrow.com"),
            ("eu", "eu", "https://eu-api.surveysparrow.com"),
            ("ap", "ap", "https://ap-api.surveysparrow.com"),
            ("me", "me", "https://me-api.surveysparrow.com"),
            ("uk", "uk", "https://eu-ln-api.surveysparrow.com"),
            ("sydney", "ap-sy", "https://ap-sy-app.surveysparrow.com"),
            ("ca", "ca", "https://ca-api.surveysparrow.com"),
        ]
    )
    def test_base_url_for(self, _name: str, data_center: str, expected: str) -> None:
        assert _base_url_for(_config(data_center=data_center)) == expected

    def test_unknown_data_center_falls_back_to_us(self) -> None:
        assert _base_url_for(_config(data_center="nope")) == "https://api.surveysparrow.com"


class TestSurveySparrowGetSchemas:
    def test_exposes_all_endpoints(self) -> None:
        schemas = SurveySparrowSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_responses_support_incremental(self) -> None:
        schemas = SurveySparrowSource().get_schemas(_config(), team_id=1)
        incremental = {s.name for s in schemas if s.supports_incremental}
        assert incremental == {"responses"}

    def test_filters_by_names(self) -> None:
        schemas = SurveySparrowSource().get_schemas(_config(), team_id=1, names=["surveys", "contacts"])
        assert {s.name for s in schemas} == {"surveys", "contacts"}


class TestSurveySparrowValidateCredentials:
    @patch(f"{SOURCE_PATCH}.validate_surveysparrow_credentials")
    def test_delegates_with_resolved_base_url(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = (True, None)

        ok, error = SurveySparrowSource().validate_credentials(_config(data_center="eu"), team_id=1)

        assert ok is True and error is None
        mock_validate.assert_called_once_with("token", "https://eu-api.surveysparrow.com")


class TestSurveySparrowResumableManager:
    def test_returns_manager_bound_to_resume_config(self) -> None:
        manager = SurveySparrowSource().get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SurveySparrowResumeConfig


class TestSurveySparrowSourceForPipeline:
    def _inputs(self, schema_name: str = "surveys") -> MagicMock:
        inputs = MagicMock()
        inputs.schema_name = schema_name
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None
        inputs.incremental_field = None
        return inputs

    def test_passes_token_base_url_and_endpoint(self) -> None:
        sentinel = cast(SourceResponse, object())
        with patch(f"{SOURCE_PATCH}.surveysparrow_source") as mock_source:
            mock_source.return_value = sentinel
            result = SurveySparrowSource().source_for_pipeline(
                _config(data_center="ca"), MagicMock(), self._inputs("responses")
            )

        assert result is sentinel
        kwargs = mock_source.call_args.kwargs
        assert kwargs["access_token"] == "token"
        assert kwargs["base_url"] == "https://ca-api.surveysparrow.com"
        assert kwargs["endpoint"] == "responses"

    def test_unknown_schema_raises(self) -> None:
        try:
            SurveySparrowSource().source_for_pipeline(_config(), MagicMock(), self._inputs("nope"))
            raise AssertionError("expected ValueError")
        except ValueError as e:
            assert "nope" in str(e)

    def test_responses_have_composite_key_and_datetime_partitioning(self) -> None:
        response = SurveySparrowSource().source_for_pipeline(_config(), MagicMock(), self._inputs("responses"))
        assert response.name == "responses"
        assert response.primary_keys == ["survey_id", "id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["completed_time"]
        assert response.sort_mode == "asc"

    def test_questions_are_unpartitioned_with_composite_key(self) -> None:
        response = SurveySparrowSource().source_for_pipeline(_config(), MagicMock(), self._inputs("questions"))
        assert response.primary_keys == ["survey_id", "id"]
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestSurveySparrowNonRetryableErrors:
    def test_marks_auth_errors_non_retryable(self) -> None:
        errors = SurveySparrowSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)
