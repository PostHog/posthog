import pytest
from unittest import mock

from parameterized import parameterized

from sources.fulcrum import source as source_module
from sources.fulcrum._config import FulcrumSourceConfig
from sources.fulcrum.source import FulcrumSource


class TestFulcrumSourceClass:
    def setup_method(self) -> None:
        self.source = FulcrumSource()
        self.config = FulcrumSourceConfig(api_token="token")
        self.team_id = 1

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Fulcrum API token"))])
    def test_validate_credentials(self, _name: str, api_result: bool, expected: tuple[bool, str | None]) -> None:
        with mock.patch.object(source_module, "validate_fulcrum_credentials", return_value=api_result):
            assert self.source.validate_credentials(self.config, self.team_id) == expected


if __name__ == "__main__":
    pytest.main([__file__])
