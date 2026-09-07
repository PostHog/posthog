import json
from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import urlparse

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rippling import (
    RipplingSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.settings import (
    ENDPOINTS,
    RIPPLING_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.source import RipplingSource

# The REST framework builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


class TestRipplingSource:
    def setup_method(self):
        self.source = RipplingSource()
        self.team_id = 123
        self.config = RipplingSourceConfig(api_token="api-token")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://rest.ripplingapis.com/workers?limit=100",
            "403 Client Error: Forbidden for url: https://rest.ripplingapis.com/compensations",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://rest.ripplingapis.com/workers",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Every Rippling list endpoint supports the standard OData-style filter.
        assert all(schema.supports_incremental for schema in schemas)
        assert all(schema.supports_append for schema in schemas)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Rippling API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.rippling.source.validate_rippling_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token)

    def test_version_declaration_defaults_to_v2_with_v1_supported(self):
        # Rippling's REST API version is bound to the token account-side, so both labels issue the
        # same requests; the default tracks the newest label without repinning existing v1 sources.
        assert self.source.supported_versions == ("v1", "v2")
        assert self.source.default_version == "v2"
        assert self.source.deprecated_versions == ()

    @pytest.mark.parametrize("pinned_version", [None, "v1", "v2"])
    @pytest.mark.parametrize("endpoint", ["workers", "work_locations"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_request_path_is_identical_for_every_version(self, mock_session, endpoint, pinned_version):
        # The pin only records which Rippling tier a source targets; it must never change the wire.
        # A future v2 branch that switched paths or injected a `Rippling-Api-Version` header would
        # break existing v1 syncs and silently override the customer's token-bound version.
        session = mock_session.return_value
        session.headers = {}
        captured: list[Any] = []

        def _prepare(request: Any) -> mock.MagicMock:
            captured.append(request)
            prepared = mock.MagicMock()
            prepared.url = request.url
            return prepared

        session.prepare_request.side_effect = _prepare
        page = Response()
        page.status_code = 200
        page._content = json.dumps({"results": [], "next_link": None}).encode()
        session.send.return_value = page

        inputs = mock.MagicMock()
        inputs.schema_name = endpoint
        inputs.api_version = pinned_version
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None
        inputs.incremental_field = None
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        response = self.source.source_for_pipeline(self.config, manager, inputs)
        list(cast(Iterable[Any], response.items()))

        assert captured, "expected at least one request"
        assert urlparse(captured[0].url).path == RIPPLING_ENDPOINTS[endpoint].path
        assert "Rippling-Api-Version" not in (captured[0].headers or {})
