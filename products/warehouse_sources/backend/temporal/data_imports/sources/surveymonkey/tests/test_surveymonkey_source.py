from typing import Literal

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.surveymonkey import (
    SurveyMonkeySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.source import (
    SurveyMonkeySource,
    _base_url_for,
)


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

    def test_surveys_response_partitions_by_date_created(self) -> None:
        response = SurveyMonkeySource().source_for_pipeline(_config(), MagicMock(), self._inputs("surveys"))
        assert response.name == "surveys"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date_created"]
        assert response.sort_mode == "asc"
