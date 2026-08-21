from typing import Literal

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.surveymonkey import (
    SurveyMonkeySourceConfig,
)
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
    def test_only_surveys_and_responses_support_incremental(self) -> None:
        schemas = SurveyMonkeySource().get_schemas(_config(), team_id=1)
        incremental = {s.name for s in schemas if s.supports_incremental}
        assert incremental == {"surveys", "survey_responses"}
