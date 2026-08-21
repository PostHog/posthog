import json
from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import urlparse

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kustomer import (
    KustomerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.source import KustomerSource

# The REST framework builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


class TestKustomerSource:
    def setup_method(self):
        self.source = KustomerSource()
        self.team_id = 123
        self.config = KustomerSourceConfig(org_name="myorg", api_key="api-key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Kustomer API credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.source.validate_kustomer_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.org_name, self.config.api_key)

    def test_version_declaration_defaults_to_v2_with_v1_supported(self):
        # Both labels resolve to the same /v1/ requests, so the default tracks the newest label.
        assert self.source.supported_versions == ("v1", "v2")
        assert self.source.default_version == "v2"
        assert self.source.deprecated_versions == ()

    @pytest.mark.parametrize("pinned_version", [None, "v1", "v2"])
    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_requests_v1_rest_paths_for_every_version(self, mock_session, endpoint, pinned_version):
        # Every list resource is served at /v1/ for both vendor versions; a v2 pin
        # must not switch to /v2/, which would 404 the stream. Covering all six also
        # guards against a per-resource /v2/ typo in the endpoint catalog.
        session = mock_session.return_value
        session.headers = {}
        captured: list[str] = []

        def _prepare(request: Any) -> mock.MagicMock:
            captured.append(request.url)
            prepared = mock.MagicMock()
            prepared.url = request.url
            return prepared

        session.prepare_request.side_effect = _prepare
        page = Response()
        page.status_code = 200
        page._content = json.dumps({"data": [], "links": {}}).encode()
        session.send.return_value = page

        inputs = mock.MagicMock()
        inputs.schema_name = endpoint
        inputs.api_version = pinned_version
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        response = self.source.source_for_pipeline(self.config, manager, inputs)
        list(cast(Iterable[Any], response.items()))

        assert captured, "expected at least one request"
        assert urlparse(captured[0]).path == f"/v1/{endpoint}"
