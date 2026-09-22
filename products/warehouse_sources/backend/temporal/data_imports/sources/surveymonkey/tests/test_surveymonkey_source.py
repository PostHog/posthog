from typing import Literal, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.surveymonkey import (
    SurveyMonkeySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.source import (
    SurveyMonkeySource,
    _base_url_for,
)

SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.source"


def _config(access_token: str = "token", data_center: Literal["us", "eu", "ca"] = "us") -> SurveyMonkeySourceConfig:
    return SurveyMonkeySourceConfig(access_token=access_token, data_center=data_center)


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
