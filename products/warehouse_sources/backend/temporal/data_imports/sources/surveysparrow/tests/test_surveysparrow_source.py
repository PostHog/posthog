from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.surveysparrow import (
    SurveySparrowSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.source import (
    SurveySparrowSource,
    _base_url_for,
)


def _config(access_token: str = "token", data_center: str = "us") -> SurveySparrowSourceConfig:
    return SurveySparrowSourceConfig(access_token=access_token, data_center=data_center)  # type: ignore[arg-type]


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


class TestSurveySparrowSourceForPipeline:
    def _inputs(self, schema_name: str = "surveys") -> MagicMock:
        inputs = MagicMock()
        inputs.schema_name = schema_name
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None
        inputs.incremental_field = None
        return inputs

    def test_unknown_schema_raises(self) -> None:
        try:
            SurveySparrowSource().source_for_pipeline(_config(), MagicMock(), self._inputs("nope"))
            raise AssertionError("expected ValueError")
        except ValueError as e:
            assert "nope" in str(e)

    def test_questions_are_unpartitioned_with_composite_key(self) -> None:
        response = SurveySparrowSource().source_for_pipeline(_config(), MagicMock(), self._inputs("questions"))
        assert response.primary_keys == ["survey_id", "id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
