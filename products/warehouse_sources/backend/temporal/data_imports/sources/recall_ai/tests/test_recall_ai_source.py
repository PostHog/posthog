import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recallai import (
    RecallAISourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recall_ai.source import RecallAISource

_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.recall_ai.source.validate_recall_ai_credentials"
)


class TestRecallAIValidateCredentials:
    @pytest.mark.parametrize(
        "region",
        [
            "us-east-1.recall.ai",
            "https://us-east-1.recall.ai",
            "us-central-1",
            "",
        ],
    )
    def test_rejects_unknown_region_without_calling_the_api(self, region: str) -> None:
        config = RecallAISourceConfig(api_key="key", region=region)
        with patch(_VALIDATE) as mock_validate:
            is_valid, message = RecallAISource().validate_credentials(config, team_id=1)
        assert is_valid is False
        assert message is not None and "us-east-1" in message
        mock_validate.assert_not_called()

    @pytest.mark.parametrize(
        ("probe_result", "expected_valid"),
        [
            ((True, 200), True),
            ((False, 401), False),
        ],
    )
    def test_maps_probe_result_to_user_message(self, probe_result: tuple[bool, int], expected_valid: bool) -> None:
        config = RecallAISourceConfig(api_key="key", region="eu-central-1")
        with patch(_VALIDATE, return_value=probe_result) as mock_validate:
            is_valid, message = RecallAISource().validate_credentials(config, team_id=1)

        assert is_valid is expected_valid
        mock_validate.assert_called_once_with("key", "eu-central-1")
        if expected_valid:
            assert message is None
        else:
            # The API key and the region must match, so a failed probe points at both.
            assert message is not None and "region" in message
