from typing import cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.surveysparrow import (
    SurveySparrowSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.source import (
    SurveySparrowSource,
    _base_url_for,
)

SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.source"


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

    def test_unknown_data_center_falls_back_to_us(self) -> None:
        assert _base_url_for(_config(data_center="nope")) == "https://api.surveysparrow.com"


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
