from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.render import RenderSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.render import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.render.source import RenderSource


class TestRenderSource:
    def setup_method(self) -> None:
        self.source = RenderSource()
        self.config = RenderSourceConfig(api_key="rnd_test", owner_id="tea-123")

    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected_valid: bool) -> None:
        with patch.object(source_module, "validate_render_credentials", return_value=probe_result):
            valid, error = self.source.validate_credentials(self.config, team_id=1)

        assert valid == expected_valid
        assert (error is None) == expected_valid

    def test_non_retryable_errors_match_requests_error_format(self) -> None:
        # The pipeline disables a source by substring-matching these keys against the raised
        # error; they must match the message `requests.raise_for_status` actually produces.
        response = MagicMock(spec=requests.Response)
        response.status_code = 401
        response.reason = "Unauthorized"
        response.url = "https://api.render.com/v1/services?limit=100"
        error = requests.HTTPError(f"401 Client Error: Unauthorized for url: {response.url}", response=response)

        assert any(key in str(error) for key in self.source.get_non_retryable_errors())
