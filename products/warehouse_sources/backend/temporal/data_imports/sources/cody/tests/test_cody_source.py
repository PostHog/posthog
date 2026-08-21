from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cody.cody import (
    CodyCredentialsError,
    CodyRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cody.source import CodySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cody import CodySourceConfig

ALL_ENDPOINTS = [
    "usage_by_user",
    "usage_by_user_month",
    "usage_by_user_day",
    "usage_by_user_day_client_language",
    "credits",
]


class TestCodySource:
    def setup_method(self):
        self.source = CodySource()
        self.config = CodySourceConfig(instance_url="example.sourcegraphcloud.com", access_token="token")
        self.team_id = 123

    def test_validate_credentials_success(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cody.source.validate_cody_credentials",
            return_value=True,
        ) as validate:
            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

        validate.assert_called_once_with("token", "example.sourcegraphcloud.com")

    @parameterized.expand(
        [
            (CodyCredentialsError("Sourcegraph rejected the access token."), "Sourcegraph rejected the access token."),
            (CodyRetryableError("status=503"), "Could not reach Sourcegraph Analytics"),
            (requests.ConnectionError("boom"), "Could not reach Sourcegraph Analytics"),
        ]
    )
    def test_validate_credentials_failure_messages(self, raised, expected_prefix):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cody.source.validate_cody_credentials",
            side_effect=raised,
        ):
            valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert valid is False
        assert message is not None and message.startswith(expected_prefix)
