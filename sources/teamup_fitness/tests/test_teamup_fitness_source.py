import pytest
from unittest.mock import patch

from sources.teamup_fitness._config import TeamupFitnessSourceConfig
from sources.teamup_fitness.settings import PROVIDER_ERROR
from sources.teamup_fitness.source import TeamupFitnessSource


@pytest.mark.parametrize("provider_id", ["", "example", "https://example.com", "123\r\nX-Header: value", "１２３"])
def test_invalid_provider_id_does_not_make_request(provider_id: str) -> None:
    config = TeamupFitnessSourceConfig(m2m_token="example-m2m-token", provider_id=provider_id)
    with patch("sources.teamup_fitness.source.validate_teamup_credentials") as validate:
        assert TeamupFitnessSource().validate_credentials(config, team_id=1) == (False, PROVIDER_ERROR)
        validate.assert_not_called()
