import json
from collections.abc import Iterable
from typing import Any, cast

from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.glassfrog import (
    GlassfrogSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.glassfrog import (
    glassfrog,
    source as source_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.glassfrog.source import GlassfrogSource


def _config() -> GlassfrogSourceConfig:
    return GlassfrogSourceConfig(api_key="gf_test_key")


class TestGlassfrogCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    @patch.object(source_module, "validate_glassfrog_credentials")
    def test_validate_credentials(
        self, _name: str, probe_result: bool, expected_ok: bool, mock_validate: MagicMock
    ) -> None:
        mock_validate.return_value = probe_result

        ok, error = GlassfrogSource().validate_credentials(_config(), team_id=1)

        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestGlassfrogPipelineHandoff:
    @patch.object(glassfrog, "make_tracked_session")
    def test_source_for_pipeline_plumbs_endpoint_and_key(self, mock_session_factory: MagicMock) -> None:
        session = MagicMock()
        session.headers = {}
        prepared_requests: list[requests.PreparedRequest] = []

        def _prepare(request: requests.Request) -> requests.PreparedRequest:
            prepared = request.prepare()
            prepared_requests.append(prepared)
            return prepared

        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"circles": [{"id": 1, "name": "General Company Circle"}]}).encode()
        session.prepare_request.side_effect = _prepare
        session.send.return_value = response
        mock_session_factory.return_value = session

        inputs = MagicMock()
        inputs.schema_name = "circles"
        inputs.team_id = 1
        inputs.job_id = "job_1"

        source_response = GlassfrogSource().source_for_pipeline(_config(), inputs)

        assert source_response.name == "circles"
        assert source_response.primary_keys == ["id"]

        # The items thunk should actually pull rows using the configured key/endpoint.
        rows = list(cast(Iterable[Any], source_response.items()))
        assert rows == [[{"id": 1, "name": "General Company Circle"}]]
        assert prepared_requests[0].headers["X-Auth-Token"] == "gf_test_key"
