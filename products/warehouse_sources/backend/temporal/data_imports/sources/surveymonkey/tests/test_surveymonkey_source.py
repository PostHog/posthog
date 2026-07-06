from typing import Literal, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SurveyMonkeySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.source import (
    SurveyMonkeySource,
    _base_url_for,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.surveymonkey import (
    SurveyMonkeyResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.source"


def _config(access_token: str = "token", data_center: Literal["us", "eu", "ca"] = "us") -> SurveyMonkeySourceConfig:
    return SurveyMonkeySourceConfig(access_token=access_token, data_center=data_center)


class TestSurveyMonkeySourceType:
    def test_source_type(self) -> None:
        assert SurveyMonkeySource().source_type == ExternalDataSourceType.SURVEYMONKEY


class TestSurveyMonkeySourceConfigFields:
    def test_exposes_access_token_and_data_center(self) -> None:
        cfg = SurveyMonkeySource().get_source_config

        names = {f.name for f in cfg.fields}
        assert names == {"access_token", "data_center"}

        token_field = next(f for f in cfg.fields if f.name == "access_token")
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.required is True
        assert token_field.secret is True

        dc_field = next(f for f in cfg.fields if f.name == "data_center")
        assert isinstance(dc_field, SourceFieldSelectConfig)
        assert dc_field.defaultValue == "us"
        assert {opt.value for opt in dc_field.options} == {"us", "eu", "ca"}

    def test_is_released_alpha(self) -> None:
        cfg = SurveyMonkeySource().get_source_config
        assert not cfg.unreleasedSource
        assert cfg.releaseStatus == ReleaseStatus.ALPHA


class TestBaseUrlFor:
    @parameterized.expand(
        [
            ("us", "us", "https://api.surveymonkey.com/v3"),
            ("eu", "eu", "https://api.eu.surveymonkey.com/v3"),
            ("ca", "ca", "https://api.surveymonkey.ca/v3"),
        ]
    )
    def test_base_url_for(self, _name: str, data_center: Literal["us", "eu", "ca"], expected: str) -> None:
        assert _base_url_for(_config(data_center=data_center)) == expected


class TestSurveyMonkeyGetSchemas:
    def test_exposes_all_endpoints(self) -> None:
        schemas = SurveyMonkeySource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_surveys_and_responses_support_incremental(self) -> None:
        schemas = SurveyMonkeySource().get_schemas(_config(), team_id=1)
        incremental = {s.name for s in schemas if s.supports_incremental}
        assert incremental == {"surveys", "survey_responses"}

    def test_full_refresh_endpoints_have_no_incremental_fields(self) -> None:
        schemas = {s.name: s for s in SurveyMonkeySource().get_schemas(_config(), team_id=1)}
        for name in ("survey_pages", "survey_questions", "collectors"):
            assert schemas[name].incremental_fields == []
            assert schemas[name].supports_incremental is False

    def test_filters_by_names(self) -> None:
        schemas = SurveyMonkeySource().get_schemas(_config(), team_id=1, names=["surveys", "collectors"])
        assert {s.name for s in schemas} == {"surveys", "collectors"}


class TestSurveyMonkeyValidateCredentials:
    @patch(f"{SOURCE_PATCH}.validate_surveymonkey_credentials")
    def test_delegates_with_resolved_base_url(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = (True, None)

        ok, error = SurveyMonkeySource().validate_credentials(_config(data_center="eu"), team_id=1)

        assert ok is True and error is None
        mock_validate.assert_called_once_with("token", "https://api.eu.surveymonkey.com/v3")


class TestSurveyMonkeyResumableManager:
    def test_returns_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = SurveyMonkeySource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SurveyMonkeyResumeConfig


class TestSurveyMonkeySourceForPipeline:
    def _inputs(self, schema_name: str = "surveys") -> MagicMock:
        inputs = MagicMock()
        inputs.schema_name = schema_name
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None
        inputs.incremental_field = None
        return inputs

    def test_passes_token_base_url_and_endpoint(self) -> None:
        sentinel = cast(SourceResponse, object())
        with patch(f"{SOURCE_PATCH}.surveymonkey_source") as mock_source:
            mock_source.return_value = sentinel
            result = SurveyMonkeySource().source_for_pipeline(
                _config(data_center="ca"), MagicMock(), self._inputs("survey_responses")
            )

        assert result is sentinel
        kwargs = mock_source.call_args.kwargs
        assert kwargs["access_token"] == "token"
        assert kwargs["base_url"] == "https://api.surveymonkey.ca/v3"
        assert kwargs["endpoint"] == "survey_responses"

    def test_surveys_response_partitions_by_date_created(self) -> None:
        response = SurveyMonkeySource().source_for_pipeline(_config(), MagicMock(), self._inputs("surveys"))
        assert response.name == "surveys"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date_created"]
        assert response.sort_mode == "asc"

    def test_questions_response_is_unpartitioned(self) -> None:
        response = SurveyMonkeySource().source_for_pipeline(_config(), MagicMock(), self._inputs("survey_questions"))
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestSurveyMonkeyNonRetryableErrors:
    def test_marks_auth_errors_non_retryable(self) -> None:
        errors = SurveyMonkeySource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)
