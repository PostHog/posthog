import pytest
from unittest.mock import MagicMock, patch

from sources.demodesk._config import DemodeskSourceConfig
from sources.demodesk.source import DemodeskSource
from sources.sdk import ResumableSourceManager, SourceInputs

_VALIDATE = "sources.demodesk.source.validate_demodesk_credentials"


class TestDemodeskSourceValidateCredentials:
    def test_rejects_non_ascii_key_without_calling_the_api(self) -> None:
        config = DemodeskSourceConfig(api_key="key​with-invisible-char")
        with patch(_VALIDATE) as mock_validate:
            is_valid, message = DemodeskSource().validate_credentials(config, team_id=1)

        assert is_valid is False
        assert message is not None and "unsupported character" in message
        mock_validate.assert_not_called()

    def test_forwards_ascii_key_to_the_api_probe(self) -> None:
        config = DemodeskSourceConfig(api_key="plain-key")
        with patch(_VALIDATE, return_value=(True, None)) as mock_validate:
            assert DemodeskSource().validate_credentials(config, team_id=1) == (True, None)
        mock_validate.assert_called_once_with("plain-key")


class TestDemodeskSourceForPipeline:
    def test_unknown_schema_raises(self) -> None:
        inputs = MagicMock(spec=SourceInputs)
        inputs.schema_name = "not_a_demodesk_table"
        manager = MagicMock(spec=ResumableSourceManager)

        with pytest.raises(ValueError, match="no schema named"):
            DemodeskSource().source_for_pipeline(DemodeskSourceConfig(api_key="key"), manager, inputs)
